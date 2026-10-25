"""Application sequencing for desired-entry reconciliation."""

from dataclasses import replace

from strategy_runtime.runtime.entry_reconciliation import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryDeclinedOutcome,
    EntryReconciliationCommand,
    EntryReconciliationInvariantError,
    NoOp,
    Replace,
    apply_success_confirmation,
    build_entry_reconciliation_command,
    decide_entry_reconciliation,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator.ports import (
    EntryAppliedJournalPort,
    EntryDeclinedJournalPort,
    EntryReconciliationExecutionPort,
)
from strategy_runtime.runtime.routing.models import LiveEntryProjectedStrategyInstance
from strategy_runtime.runtime.state.identity import TradeCycleIdFactory
from strategy_runtime.runtime.state.models import PendingEntryRecovery, StrategyInstanceRuntimeState
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository


class EntryReconciliationOrchestrator:
    """Coordinate one reconciliation decision through acknowledged execution."""

    def __init__(
        self,
        trade_cycle_id_factory: TradeCycleIdFactory,
        execution_port: EntryReconciliationExecutionPort,
        state_repository: StrategyInstanceRuntimeStateRepository,
        entry_applied_journal: EntryAppliedJournalPort | None = None,
        entry_declined_journal: EntryDeclinedJournalPort | None = None,
    ) -> None:
        self._trade_cycle_id_factory = trade_cycle_id_factory
        self._execution_port = execution_port
        self._state_repository = state_repository
        self._entry_applied_journal = entry_applied_journal
        self._entry_declined_journal = entry_declined_journal

    def execute(
        self,
        projection: LiveEntryProjectedStrategyInstance,
    ) -> StrategyInstanceRuntimeState:
        """Return unchanged source state or one confirmed replacement aggregate."""
        source_state = projection.source.resolved_state.runtime_state
        decision = decide_entry_reconciliation(
            projection.desired_entry,
            source_state.current_trade_cycle,
        )
        if type(decision) is NoOp:
            return source_state
        if type(decision) is Replace:
            # Confirmed CANCEL first; APPLY is sent only after absence is
            # confirmed, from the absent state durably re-marked with the new
            # identity (the boundary save inside the second step).
            absent_state = self._execute_one(
                projection, source_state, Cancel(decision.trade_cycle_id), None
            )
            return self._execute_one(
                projection,
                absent_state,
                Apply(decision.desired_entry),
                self._trade_cycle_id_factory(),
            )
        if type(decision) is Apply:
            return self._execute_one(
                projection, source_state, decision, self._trade_cycle_id_factory()
            )
        if type(decision) is Cancel:
            return self._execute_one(projection, source_state, decision, None)
        raise EntryReconciliationInvariantError(
            "unknown command-bearing entry reconciliation decision"
        )

    def _execute_one(
        self,
        projection: LiveEntryProjectedStrategyInstance,
        state: StrategyInstanceRuntimeState,
        decision: Apply | Cancel,
        apply_trade_cycle_id: str | None,
    ) -> StrategyInstanceRuntimeState:
        command = build_entry_reconciliation_command(
            state,
            decision,
            apply_trade_cycle_id,
        )
        if type(command) is not EntryReconciliationCommand:
            raise EntryReconciliationInvariantError(
                "command-bearing reconciliation decision must produce a command"
            )

        pending_state = self._state_repository.save(
            replace(
                state,
                pending_entry_recovery=PendingEntryRecovery(command.trade_cycle_id),
            )
        )

        confirmation = self._execution_port.execute(command, state)
        if isinstance(confirmation, EntryDeclinedOutcome):
            return self._end_declined_apply(
                projection, pending_state, decision, command, confirmation
            )
        if type(confirmation) not in {EntryAppliedConfirmation, EntryAbsentConfirmation}:
            raise EntryReconciliationInvariantError(
                "execution port must return a successful entry confirmation"
            )

        if type(confirmation) is EntryAppliedConfirmation:
            self._journal_entry_applied(
                confirmation,
                projection.source.processing_unit.committed_bar.open_time_ms,
            )

        return apply_success_confirmation(
            pending_state,
            decision,
            command,
            confirmation,
        )

    def _end_declined_apply(
        self,
        projection: LiveEntryProjectedStrategyInstance,
        pending_state: StrategyInstanceRuntimeState,
        decision: Apply | Cancel,
        command: EntryReconciliationCommand,
        declined: EntryDeclinedOutcome,
    ) -> StrategyInstanceRuntimeState:
        # An expected refusal before the exchange: no cycle, no recovery. The
        # cleared state is saved here because for a plain Apply it equals the
        # bar's source state, and the caller skips saving an unchanged state.
        if type(decision) is not Apply:
            raise EntryReconciliationInvariantError("only APPLY may be declined")
        if (
            declined.strategy_instance_id != command.strategy_instance_id
            or declined.trade_cycle_id != command.trade_cycle_id
        ):
            raise EntryReconciliationInvariantError(
                "declined outcome does not match the sent command"
            )
        saved_state = self._state_repository.save(
            replace(pending_state, pending_entry_recovery=None)
        )
        if self._entry_declined_journal is not None:
            self._entry_declined_journal.entry_package_declined(
                strategy_instance_id=declined.strategy_instance_id,
                trade_cycle_id=declined.trade_cycle_id,
                bar_open_time_ms=projection.source.processing_unit.committed_bar.open_time_ms,
                risk_multiplier=pending_state.risk_multiplier,
                decline_reason=declined.decline_reason,
                decline_message=declined.decline_message,
            )
        return saved_state

    def _journal_entry_applied(
        self, confirmation: EntryAppliedConfirmation, bar_open_time_ms: int
    ) -> None:
        if self._entry_applied_journal is None:
            return
        if (
            confirmation.trigger_price is None
            and confirmation.stop_loss is None
            and confirmation.take_profit is None
            and confirmation.quantity is None
            and confirmation.order_link_id is None
            and confirmation.order_id is None
        ):
            return
        self._entry_applied_journal.entry_package_applied(
            strategy_instance_id=confirmation.strategy_instance_id,
            trade_cycle_id=confirmation.trade_cycle_id,
            bar_open_time_ms=bar_open_time_ms,
            trigger_price=confirmation.trigger_price,
            stop_loss=confirmation.stop_loss,
            take_profit=confirmation.take_profit,
            quantity=confirmation.quantity,
            order_link_id=confirmation.order_link_id,
            order_id=confirmation.order_id,
        )
