"""One bounded resolution attempt for a durable `pending_entry_recovery` marker.

Runs independently of committed-bar cadence (see `committed_bar_intake`). Each
attempt holds the same `StrategyInstanceKeyedMutexRegistry` bar processing and
the first-fill webhook path already share, performs at most one bounded ABI
recovery-state query plus, in exactly one case, one bounded corrective CANCEL,
and applies no wall-clock gate of any kind: whether an attempt resolves
depends entirely on ABI's response, never on elapsed time.
"""

from dataclasses import replace

from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryClientError,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import (
    EntryOrderLiveRecoveryState,
    PositionOpenRecoveryState,
    RecoveryStateAppliedEntryPackage,
    RecoveryStateResponse,
    TerminalAfterFillRecoveryState,
    TerminalWithoutFillRecoveryState,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_ports import AbiEntryCycleRecoveryPort
from strategy_runtime.runtime.abi.entry_package_models import EntryPackageWireDesiredEntry
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.first_fill.state_applier import apply_first_fill
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository


class UncertainExchangeStateResolver:
    """Resolve one instance's `pending_entry_recovery` against ABI's recovery-state endpoint."""

    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        abi_entry_cycle_recovery: AbiEntryCycleRecoveryPort,
    ) -> None:
        self._state_repository = state_repository
        self._keyed_mutex_registry = keyed_mutex_registry
        self._abi_entry_cycle_recovery = abi_entry_cycle_recovery

    def attempt(self, strategy_instance_id: str) -> None:
        """Resolve, or leave untouched, the one instance's pending recovery marker."""
        with self._keyed_mutex_registry.hold(strategy_instance_id):
            state = self._state_repository.get(strategy_instance_id)
            if state is None or state.pending_entry_recovery is None:
                return

            trade_cycle_id = state.pending_entry_recovery.trade_cycle_id
            try:
                response = self._abi_entry_cycle_recovery.query(
                    strategy_instance_id, trade_cycle_id
                )
            except AbiEntryCycleRecoveryClientError:
                # Transport failure, availability failure, inconclusive-evidence
                # safe error, or unknown-binding error: all leave the marker
                # untouched (see design.md Decision 4).
                return

            if state.current_trade_cycle is None:
                self._resolve_uncertain_apply(state, trade_cycle_id, response)
            else:
                self._resolve_uncertain_removal(state, state.current_trade_cycle, response)

    def _resolve_uncertain_apply(
        self,
        state: StrategyInstanceRuntimeState,
        trade_cycle_id: str,
        response: RecoveryStateResponse,
    ) -> None:
        if isinstance(response, (EntryOrderLiveRecoveryState, PositionOpenRecoveryState)):
            reconstructed = replace(
                state,
                current_trade_cycle=_build_cycle(trade_cycle_id, response.applied_entry_package),
                pending_entry_recovery=None,
            )
            if isinstance(response, PositionOpenRecoveryState):
                reconstructed = apply_first_fill(
                    reconstructed, trade_cycle_id, response.first_fill_at_ms
                )
            self._state_repository.save(reconstructed)
            return

        if isinstance(
            response, (TerminalWithoutFillRecoveryState, TerminalAfterFillRecoveryState)
        ):
            self._state_repository.save(
                replace(state, current_trade_cycle=None, pending_entry_recovery=None)
            )

    def _resolve_uncertain_removal(
        self,
        state: StrategyInstanceRuntimeState,
        current_cycle: CurrentTradeCycle,
        response: RecoveryStateResponse,
    ) -> None:
        if isinstance(
            response, (TerminalWithoutFillRecoveryState, TerminalAfterFillRecoveryState)
        ):
            self._state_repository.save(
                replace(state, current_trade_cycle=None, pending_entry_recovery=None)
            )
            return

        if isinstance(response, PositionOpenRecoveryState):
            # The removal lost the race to a fill; the ordinary bar path's
            # open-position resolution and position management take over.
            self._state_repository.save(replace(state, pending_entry_recovery=None))
            return

        if isinstance(response, EntryOrderLiveRecoveryState):
            # The only corrective action this component performs. The marker
            # stays set for a later attempt to observe the outcome.
            self._abi_entry_cycle_recovery.cancel(
                state.strategy_instance_id,
                current_cycle.trade_cycle_id,
                state.registered_spec_snapshot.instrument,
                state.risk_multiplier,
            )


def _build_cycle(
    trade_cycle_id: str, applied: RecoveryStateAppliedEntryPackage
) -> CurrentTradeCycle:
    return CurrentTradeCycle(
        trade_cycle_id=trade_cycle_id,
        applied_entry_package=AppliedEntryPackage(
            applied_desired_entry=_decode_desired_entry(applied.applied_desired_entry),
            calculated_quantity=applied.calculated_quantity,
        ),
    )


def _decode_desired_entry(value: EntryPackageWireDesiredEntry) -> DesiredEntry:
    return DesiredEntry(
        side=value.side,
        source_plan_bar_open_time_ms=value.source_plan_bar_open_time_ms,
        planned_entry_price=value.planned_entry_price,
        initial_stop_price=value.initial_stop_price,
        initial_take_price=value.initial_take_price,
        locked_exit_profile=value.locked_exit_profile,
    )
