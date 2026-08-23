"""Application sequencing for position-management execution."""

from dataclasses import replace

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
    apply_position_management_confirmation,
    build_position_management_command,
)
from strategy_runtime.runtime.position_management_orchestrator.ports import (
    PositionManagementExecutionPort,
)
from strategy_runtime.runtime.routing.models import OpenTradeProjectedStrategyInstance
from strategy_runtime.runtime.state.models import PendingCloseRecovery, StrategyInstanceRuntimeState
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository


class PositionManagementOrchestrator:
    """Coordinate one position-management decision through confirmed execution."""

    def __init__(
        self,
        execution_port: PositionManagementExecutionPort,
        state_repository: StrategyInstanceRuntimeStateRepository,
    ) -> None:
        self._execution_port = execution_port
        self._state_repository = state_repository

    def execute(
        self,
        projection: OpenTradeProjectedStrategyInstance,
    ) -> StrategyInstanceRuntimeState:
        """Return unchanged source state or one confirmed replacement aggregate."""
        source_state = projection.source.resolved_state.runtime_state
        decision = decide_position_management(
            projection.position_management_recipe,
            source_state.current_trade_cycle,
        )
        if type(decision) is NoOp:
            return source_state

        command = build_position_management_command(source_state, decision)

        if type(decision) is ApplyProtection:
            if type(command) is not ApplyProtectionCommand:
                raise PositionManagementExecutionInvariantError(
                    "APPLY_PROTECTION must produce an ApplyProtectionCommand"
                )
            protection_confirmation = self._execution_port.apply_protection(command)
            return apply_position_management_confirmation(
                source_state,
                decision,
                command,
                protection_confirmation,
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
            return apply_position_management_confirmation(
                pending_state,
                decision,
                command,
                close_confirmation,
            )

        raise PositionManagementExecutionInvariantError(
            "unknown command-bearing position-management decision"
        )
