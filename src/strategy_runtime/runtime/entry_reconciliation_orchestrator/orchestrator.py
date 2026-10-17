"""Application sequencing for desired-entry reconciliation."""

from dataclasses import replace

from strategy_runtime.runtime.entry_reconciliation import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    EntryReconciliationInvariantError,
    NoOp,
    apply_success_confirmation,
    build_entry_reconciliation_command,
    decide_entry_reconciliation,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator.ports import (
    EntryAppliedJournalPort,
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
    ) -> None:
        self._trade_cycle_id_factory = trade_cycle_id_factory
        self._execution_port = execution_port
        self._state_repository = state_repository
        self._entry_applied_journal = entry_applied_journal

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

        apply_trade_cycle_id = self._trade_cycle_id_factory() if type(decision) is Apply else None
        command = build_entry_reconciliation_command(
            source_state,
            decision,
            apply_trade_cycle_id,
        )
        if type(command) is not EntryReconciliationCommand:
            raise EntryReconciliationInvariantError(
                "command-bearing reconciliation decision must produce a command"
            )

        pending_state = self._state_repository.save(
            replace(
                source_state,
                pending_entry_recovery=PendingEntryRecovery(command.trade_cycle_id),
            )
        )

        confirmation = self._execution_port.execute(command, source_state)
        if type(confirmation) not in {EntryAppliedConfirmation, EntryAbsentConfirmation}:
            raise EntryReconciliationInvariantError(
                "execution port must return a successful entry confirmation"
            )

        if type(confirmation) is EntryAppliedConfirmation:
            self._journal_entry_applied(
                confirmation,
                projection.source.processing_unit.committed_bar.open_time_ms,
            )

        if isinstance(decision, (Apply, Cancel)):
            return apply_success_confirmation(
                pending_state,
                decision,
                command,
                confirmation,
            )
        raise EntryReconciliationInvariantError(
            "unknown command-bearing entry reconciliation decision"
        )

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
