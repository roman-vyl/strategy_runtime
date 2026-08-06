"""Pure position-management decision selection."""

from strategy_runtime.runtime.position_management_decision.errors import (
    PositionManagementDecisionInvariantError,
)
from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
    PositionManagementDecision,
)
from strategy_runtime.runtime.recipes.position_management import (
    DesiredProtection,
    PositionManagementRecipe,
)
from strategy_runtime.runtime.state.models import CurrentTradeCycle


def resolve_effective_acknowledged_protection(
    current_trade_cycle: CurrentTradeCycle,
) -> DesiredProtection:
    """Return the effective acknowledged protection for a frozen current cycle."""
    if type(current_trade_cycle) is not CurrentTradeCycle:
        raise TypeError("current_trade_cycle must be CurrentTradeCycle")
    if current_trade_cycle.frozen_entry_context is None:
        raise PositionManagementDecisionInvariantError(
            "resolving acknowledged protection requires a frozen entry context"
        )
    if current_trade_cycle.latest_confirmed_management_protection is not None:
        return current_trade_cycle.latest_confirmed_management_protection

    desired_entry = current_trade_cycle.frozen_entry_context.desired_entry
    return DesiredProtection(
        stop_price=desired_entry.initial_stop_price,
        take_price=desired_entry.initial_take_price,
    )


def decide_position_management(
    recipe: PositionManagementRecipe,
    current_trade_cycle: CurrentTradeCycle | None,
) -> PositionManagementDecision:
    """Select the complete position-management decision for one recipe."""
    if type(recipe) is not PositionManagementRecipe:
        raise TypeError("recipe must be PositionManagementRecipe")
    if current_trade_cycle is None:
        raise PositionManagementDecisionInvariantError(
            "position-management decision requires an existing current trade cycle"
        )
    if type(current_trade_cycle) is not CurrentTradeCycle:
        raise TypeError("current_trade_cycle must be CurrentTradeCycle or None")
    if current_trade_cycle.frozen_entry_context is None:
        raise PositionManagementDecisionInvariantError(
            "position-management decision requires a frozen entry context"
        )

    if recipe.close_signal.active:
        return ClosePosition(current_trade_cycle.trade_cycle_id, recipe.close_signal)

    effective_protection = resolve_effective_acknowledged_protection(current_trade_cycle)
    if recipe.desired_protection == effective_protection:
        return NoOp()
    return ApplyProtection(current_trade_cycle.trade_cycle_id, recipe.desired_protection)
