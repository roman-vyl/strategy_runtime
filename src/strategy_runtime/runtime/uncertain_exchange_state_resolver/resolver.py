"""One bounded resolution attempt for a durable `pending_entry_recovery` marker.

Runs independently of committed-bar cadence (see `committed_bar_intake`). Each
attempt holds the same `StrategyInstanceKeyedMutexRegistry` bar processing and
the first-fill webhook path already share, performs at most one bounded ABI
recovery-state query plus, in one of two explicit state/context rows, one
bounded corrective CANCEL, and applies no wall-clock gate of any kind: whether
an attempt resolves depends entirely on ABI's response, never on elapsed time.
"""

from dataclasses import replace

from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryClientError,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import (
    EntryOrderLiveRecoveryState,
    EntryOrderNotFoundRecoveryState,
    PositionOpenRecoveryState,
    RecoveryStateAppliedEntryPackage,
    RecoveryStateResponse,
    TerminalAfterFillRecoveryState,
    TerminalWithoutFillRecoveryState,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_ports import AbiEntryCycleRecoveryPort
from strategy_runtime.runtime.abi.entry_package_errors import AbiEntryPackageClientError
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageWireDesiredEntry,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.first_fill.state_applier import apply_first_fill
from strategy_runtime.runtime.position_management_execution.models import (
    ClosePositionCommand,
    PositionClosedConfirmation,
)
from strategy_runtime.runtime.position_management_orchestrator.ports import (
    PositionManagementExecutionPort,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository


class UncertainExchangeStateResolver:
    """Resolve one instance's `pending_entry_recovery`/`pending_close_recovery`
    against ABI's recovery-state endpoint or the pair-scoped close endpoint."""

    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        abi_entry_cycle_recovery: AbiEntryCycleRecoveryPort,
        position_management_execution: PositionManagementExecutionPort,
    ) -> None:
        self._state_repository = state_repository
        self._keyed_mutex_registry = keyed_mutex_registry
        self._abi_entry_cycle_recovery = abi_entry_cycle_recovery
        self._position_management_execution = position_management_execution

    def attempt(self, strategy_instance_id: str) -> None:
        """Resolve, or leave untouched, the one instance's pending recovery marker."""
        with self._keyed_mutex_registry.hold(strategy_instance_id):
            state = self._state_repository.get(strategy_instance_id)
            if state is None:
                return
            if state.pending_close_recovery is not None:
                self._resolve_pending_close(state)
                return
            if state.pending_entry_recovery is None:
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

    def _resolve_pending_close(self, state: StrategyInstanceRuntimeState) -> None:
        pending_close_recovery = state.pending_close_recovery
        assert pending_close_recovery is not None
        trade_cycle_id = pending_close_recovery.trade_cycle_id
        command = ClosePositionCommand(
            strategy_instance_id=state.strategy_instance_id,
            trade_cycle_id=trade_cycle_id,
        )
        try:
            confirmation = self._position_management_execution.close_position(command)
        except Exception:
            # Transport failure or any other exception: leave the marker
            # untouched, eligible for another attempt on the next tick.
            return

        if (
            type(confirmation) is not PositionClosedConfirmation
            or confirmation.strategy_instance_id != state.strategy_instance_id
            or confirmation.trade_cycle_id != trade_cycle_id
        ):
            return

        current_cycle = state.current_trade_cycle
        if current_cycle is None or current_cycle.trade_cycle_id != trade_cycle_id:
            return

        self._state_repository.save(
            replace(state, current_trade_cycle=None, pending_close_recovery=None)
        )

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

        if isinstance(response, (TerminalWithoutFillRecoveryState, TerminalAfterFillRecoveryState)):
            self._state_repository.save(
                replace(state, current_trade_cycle=None, pending_entry_recovery=None)
            )
            return

        if isinstance(response, EntryOrderNotFoundRecoveryState):
            self._cancel_and_clear_only_if_exact_absent(state, trade_cycle_id)

    def _resolve_uncertain_removal(
        self,
        state: StrategyInstanceRuntimeState,
        current_cycle: CurrentTradeCycle,
        response: RecoveryStateResponse,
    ) -> None:
        if isinstance(response, (TerminalWithoutFillRecoveryState, TerminalAfterFillRecoveryState)):
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
            self._cancel_and_clear_only_if_exact_absent(state, current_cycle.trade_cycle_id)

    def _cancel_and_clear_only_if_exact_absent(
        self, state: StrategyInstanceRuntimeState, trade_cycle_id: str
    ) -> None:
        """Issue the one existing corrective CANCEL and trust only exact formal absence."""
        try:
            cancel_result = self._abi_entry_cycle_recovery.cancel(
                state.strategy_instance_id,
                trade_cycle_id,
                state.registered_spec_snapshot.instrument,
                state.risk_multiplier,
            )
        except AbiEntryPackageClientError:
            return

        if (
            type(cancel_result) is EntryPackageAbsent
            and cancel_result.strategy_instance_id == state.strategy_instance_id
            and cancel_result.trade_cycle_id == trade_cycle_id
        ):
            self._state_repository.save(
                replace(state, current_trade_cycle=None, pending_entry_recovery=None)
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
