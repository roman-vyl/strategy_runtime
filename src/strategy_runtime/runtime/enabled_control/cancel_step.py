"""The shared safety step of a disable and of a delete.

Refuse when a recovery, a position or an unsettled closure is there; cancel a resting entry
order through ABI and clear the cycle only on an exact `absent` answer.
"""

from dataclasses import replace

from strategy_runtime.runtime.abi.entry_cycle_recovery_ports import AbiEntryCycleRecoveryPort
from strategy_runtime.runtime.abi.entry_package_errors import AbiEntryPackageClientError
from strategy_runtime.runtime.abi.entry_package_models import EntryPackageAbsent
from strategy_runtime.runtime.enabled_control.errors import (
    AbiUnavailable,
    CancelNotConfirmed,
    CycleNotSettled,
    PositionOpen,
    RecoveryPending,
)
from strategy_runtime.runtime.entry_cycle_ended import (
    DISABLED,
    EntryCycleEndedJournalPort,
    journal_entry_cycle_ended,
)
from strategy_runtime.runtime.open_position.errors import OpenPositionResolutionError
from strategy_runtime.runtime.open_position.ports import OpenPositionResolverPort
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository


class EntryOrderCancelStep:
    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        open_position_resolver: OpenPositionResolverPort,
        abi_entry_cycle_recovery: AbiEntryCycleRecoveryPort,
        entry_cycle_ended_journal: EntryCycleEndedJournalPort | None = None,
    ) -> None:
        self._state_repository = state_repository
        self._open_position_resolver = open_position_resolver
        self._abi_entry_cycle_recovery = abi_entry_cycle_recovery
        self._entry_cycle_ended_journal = entry_cycle_ended_journal

    def run(self, strategy_instance_id: str) -> bool:
        """Return True when a resting entry order was cancelled and the cycle cleared."""
        state = self._state_repository.get(strategy_instance_id)
        if state is None:
            return False
        if state.pending_entry_recovery is not None or state.pending_close_recovery is not None:
            raise RecoveryPending
        cycle = state.current_trade_cycle
        if cycle is None:
            return False

        try:
            resolved = self._open_position_resolver.resolve(state)
        except OpenPositionResolutionError as exc:
            raise AbiUnavailable from exc
        if resolved.position_open:
            raise PositionOpen
        if resolved.closure is not None:
            raise CycleNotSettled

        try:
            cancel_result = self._abi_entry_cycle_recovery.cancel(
                strategy_instance_id,
                cycle.trade_cycle_id,
                state.registered_spec_snapshot.instrument,
                state.risk_multiplier,
            )
        except AbiEntryPackageClientError as exc:
            raise AbiUnavailable from exc
        if not (
            type(cancel_result) is EntryPackageAbsent
            and cancel_result.strategy_instance_id == strategy_instance_id
            and cancel_result.trade_cycle_id == cycle.trade_cycle_id
        ):
            raise CancelNotConfirmed
        self._state_repository.save(replace(state, current_trade_cycle=None))
        journal_entry_cycle_ended(
            self._entry_cycle_ended_journal,
            strategy_instance_id=strategy_instance_id,
            trade_cycle_id=cycle.trade_cycle_id,
            bar_open_time_ms=None,
            reason=DISABLED,
        )
        return True
