"""Application sequencing for position-management execution."""

from dataclasses import asdict, replace

from strategy_runtime.runtime.position_management_decision.decision import (
    decide_position_management,
)
from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
)
from strategy_runtime.runtime.position_management_execution import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionManagementExecutionInvariantError,
    ProtectionAppliedConfirmation,
    apply_position_management_confirmation,
    build_position_management_command,
)
from strategy_runtime.runtime.position_management_orchestrator.ports import (
    PositionManagementExecutionPort,
    ProtectionAppliedJournalPort,
)
from strategy_runtime.runtime.routing.models import OpenTradeProjectedStrategyInstance
from strategy_runtime.runtime.state.models import PendingCloseRecovery, StrategyInstanceRuntimeState
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure


class PositionManagementOrchestrator:
    """Coordinate one position-management decision through confirmed execution."""

    def __init__(
        self,
        execution_port: PositionManagementExecutionPort,
        state_repository: StrategyInstanceRuntimeStateRepository,
        protection_applied_journal: ProtectionAppliedJournalPort | None = None,
    ) -> None:
        self._execution_port = execution_port
        self._state_repository = state_repository
        self._protection_applied_journal = protection_applied_journal

    def execute(
        self,
        projection: OpenTradeProjectedStrategyInstance,
    ) -> StrategyInstanceRuntimeState:
        """Return unchanged source state or one confirmed replacement aggregate."""
        return self.execute_with_closure(projection)[0]

    def execute_with_closure(
        self,
        projection: OpenTradeProjectedStrategyInstance,
    ) -> tuple[StrategyInstanceRuntimeState, TradeCycleClosure | None]:
        """Like `execute`, plus ABI's closure when a confirmed close carried one."""
        source_state = projection.source.resolved_state.runtime_state
        decision = decide_position_management(
            projection.position_management_recipe,
            source_state.current_trade_cycle,
        )
        if type(decision) is NoOp:
            return source_state, None

        command = build_position_management_command(source_state, decision)

        if type(decision) is ApplyProtection:
            if type(command) is not ApplyProtectionCommand:
                raise PositionManagementExecutionInvariantError(
                    "APPLY_PROTECTION must produce an ApplyProtectionCommand"
                )
            protection_confirmation = self._execution_port.apply_protection(command)
            if type(protection_confirmation) is not ProtectionAppliedConfirmation:
                raise PositionManagementExecutionInvariantError(
                    "APPLY_PROTECTION requires ProtectionAppliedConfirmation"
                )
            # After ABI confirms, before the confirmation is applied; the save
            # stays in the caller (same order as `entry_package_applied`).
            self._journal_protection_applied(
                command,
                protection_confirmation,
                projection.source.processing_unit.committed_bar.open_time_ms,
            )
            return (
                apply_position_management_confirmation(
                    source_state,
                    decision,
                    command,
                    protection_confirmation,
                ),
                None,
            )

        if type(decision) is ClosePosition:
            if type(command) is not ClosePositionCommand:
                raise PositionManagementExecutionInvariantError(
                    "CLOSE_POSITION must produce a ClosePositionCommand"
                )
            pending_state = self._state_repository.save(
                replace(
                    source_state,
                    pending_close_recovery=PendingCloseRecovery(command.trade_cycle_id),
                )
            )
            close_confirmation = self._execution_port.close_position(command)
            return (
                apply_position_management_confirmation(
                    pending_state,
                    decision,
                    command,
                    close_confirmation,
                ),
                close_confirmation.closure,
            )

        raise PositionManagementExecutionInvariantError(
            "unknown command-bearing position-management decision"
        )

    def _journal_protection_applied(
        self,
        command: ApplyProtectionCommand,
        confirmation: ProtectionAppliedConfirmation,
        bar_open_time_ms: int,
    ) -> None:
        if self._protection_applied_journal is None:
            return
        orders = confirmation.protection_orders
        self._protection_applied_journal.protection_applied(
            strategy_instance_id=confirmation.strategy_instance_id,
            trade_cycle_id=confirmation.trade_cycle_id,
            bar_open_time_ms=bar_open_time_ms,
            requested_protection=asdict(command.desired_protection),
            confirmed_protection=asdict(confirmation.confirmed_protection),
            position_quantity=orders.quantity,
            stop_order=asdict(orders.stop),
            take_order=asdict(orders.take),
        )
