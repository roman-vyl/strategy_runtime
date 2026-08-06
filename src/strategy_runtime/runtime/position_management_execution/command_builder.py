"""Pure construction of position-management execution commands."""

from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
    PositionManagementDecision,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionManagementExecutionCommand,
)
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState


def build_position_management_command(
    state: StrategyInstanceRuntimeState,
    decision: PositionManagementDecision,
) -> PositionManagementExecutionCommand | None:
    """Build one coherent command, return no command for NoOp, or fail closed."""
    if type(state) is not StrategyInstanceRuntimeState:
        raise PositionManagementExecutionInvariantError(
            "command construction requires StrategyInstanceRuntimeState"
        )

    if type(decision) is NoOp:
        return None

    if type(decision) is ApplyProtection:
        _require_current_cycle(state, decision.trade_cycle_id, "APPLY_PROTECTION")
        return ApplyProtectionCommand(
            strategy_instance_id=state.strategy_instance_id,
            trade_cycle_id=decision.trade_cycle_id,
            desired_protection=decision.desired_protection,
        )

    if type(decision) is ClosePosition:
        _require_current_cycle(state, decision.trade_cycle_id, "CLOSE_POSITION")
        return ClosePositionCommand(
            strategy_instance_id=state.strategy_instance_id,
            trade_cycle_id=decision.trade_cycle_id,
        )

    raise PositionManagementExecutionInvariantError("unknown position-management decision")


def _require_current_cycle(
    state: StrategyInstanceRuntimeState,
    decision_trade_cycle_id: str,
    action: str,
) -> None:
    current_cycle = state.current_trade_cycle
    if current_cycle is None:
        raise PositionManagementExecutionInvariantError(
            f"{action} requires an acknowledged current trade cycle"
        )
    if current_cycle.trade_cycle_id != decision_trade_cycle_id:
        raise PositionManagementExecutionInvariantError(
            f"{action} trade_cycle_id does not match current trade cycle"
        )
