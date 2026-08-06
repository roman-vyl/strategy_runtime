from typing import Literal

import pytest

from strategy_runtime.runtime.position_management_decision.decision import (
    decide_position_management,
    resolve_effective_acknowledged_protection,
)
from strategy_runtime.runtime.position_management_decision.errors import (
    PositionManagementDecisionInvariantError,
)
from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import (
    CloseSignal,
    DesiredProtection,
    PositionManagementRecipe,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
)


def desired_entry(
    *,
    side: Literal["long", "short"] = "long",
    initial_stop_price: str = "99",
    initial_take_price: str = "103",
) -> DesiredEntry:
    return DesiredEntry(side, 900, "100", initial_stop_price, initial_take_price, "runner")


def frozen_cycle(
    *,
    trade_cycle_id: str = "cycle-1",
    entry: DesiredEntry | None = None,
    latest_confirmed_management_protection: DesiredProtection | None = None,
    frozen: bool = True,
) -> CurrentTradeCycle:
    entry = entry or desired_entry()
    frozen_entry_context = (
        FrozenExecutedEntryContext(entry, first_fill_at_ms=950, entry_bar_open_time_ms=900)
        if frozen
        else None
    )
    return CurrentTradeCycle(
        trade_cycle_id,
        AppliedEntryPackage(entry, "0.1"),
        frozen_entry_context,
        latest_confirmed_management_protection,
    )


def recipe(
    *,
    stop_price: str = "99",
    take_price: str | None = "103",
    active: bool = False,
    diagnostics: dict[str, object] | None = None,
) -> PositionManagementRecipe:
    return PositionManagementRecipe(
        desired_protection=DesiredProtection(stop_price, take_price),
        close_signal=CloseSignal(active),
        diagnostics=diagnostics or {},
    )


class TestClosePriority:
    def test_active_close_wins_with_equal_protection(self) -> None:
        cycle = frozen_cycle()
        close_signal = CloseSignal(True, reason="stop_hunt")
        active_recipe = PositionManagementRecipe(
            desired_protection=DesiredProtection("99", "103"),
            close_signal=close_signal,
            diagnostics={},
        )

        result = decide_position_management(active_recipe, cycle)

        assert result == ClosePosition("cycle-1", close_signal)

    def test_active_close_wins_with_different_protection(self) -> None:
        cycle = frozen_cycle()
        close_signal = CloseSignal(True, reason="stop_hunt")
        active_recipe = PositionManagementRecipe(
            desired_protection=DesiredProtection("50", None),
            close_signal=close_signal,
            diagnostics={},
        )

        result = decide_position_management(active_recipe, cycle)

        assert result == ClosePosition("cycle-1", close_signal)
        assert not isinstance(result, ApplyProtection)


class TestProtectionComparison:
    def test_equal_protection_is_noop(self) -> None:
        cycle = frozen_cycle(entry=desired_entry(initial_stop_price="99", initial_take_price="103"))
        unchanged = recipe(stop_price="99.00", take_price="103.0")

        assert decide_position_management(unchanged, cycle) == NoOp()

    def test_different_stop_applies_change(self) -> None:
        cycle = frozen_cycle()
        changed = recipe(stop_price="98", take_price="103")

        result = decide_position_management(changed, cycle)

        assert result == ApplyProtection("cycle-1", DesiredProtection("98", "103"))

    def test_take_price_value_to_null_applies_change(self) -> None:
        cycle = frozen_cycle()
        changed = recipe(stop_price="99", take_price=None)

        result = decide_position_management(changed, cycle)

        assert result == ApplyProtection("cycle-1", DesiredProtection("99", None))

    def test_diagnostics_do_not_affect_the_decision(self) -> None:
        cycle = frozen_cycle()
        left = recipe(stop_price="98", diagnostics={"a": 1})
        right = recipe(stop_price="98", diagnostics={"b": [1, 2, 3]})

        assert decide_position_management(left, cycle) == decide_position_management(right, cycle)


class TestEffectiveAcknowledgedProtection:
    def test_initial_frozen_protection_is_the_baseline(self) -> None:
        cycle = frozen_cycle(entry=desired_entry(initial_stop_price="90", initial_take_price="110"))

        result = resolve_effective_acknowledged_protection(cycle)

        assert result == DesiredProtection("90", "110")

    def test_latest_confirmed_protection_supersedes_the_baseline(self) -> None:
        cycle = frozen_cycle(
            entry=desired_entry(initial_stop_price="90", initial_take_price="110"),
            latest_confirmed_management_protection=DesiredProtection("95", None),
        )

        result = resolve_effective_acknowledged_protection(cycle)

        assert result == DesiredProtection("95", None)

    def test_baseline_selection_flows_through_the_decision(self) -> None:
        cycle = frozen_cycle(
            entry=desired_entry(initial_stop_price="90", initial_take_price="110"),
            latest_confirmed_management_protection=DesiredProtection("95", None),
        )
        matches_confirmed = recipe(stop_price="95", take_price=None)
        matches_initial = recipe(stop_price="90", take_price="110")

        assert decide_position_management(matches_confirmed, cycle) == NoOp()
        assert decide_position_management(matches_initial, cycle) == ApplyProtection(
            "cycle-1", DesiredProtection("90", "110")
        )


class TestFailClosed:
    def test_missing_current_trade_cycle_fails_closed(self) -> None:
        with pytest.raises(PositionManagementDecisionInvariantError):
            decide_position_management(recipe(), None)

    def test_unfrozen_current_trade_cycle_fails_closed(self) -> None:
        cycle = frozen_cycle(frozen=False)

        with pytest.raises(PositionManagementDecisionInvariantError):
            decide_position_management(recipe(), cycle)

    def test_unfrozen_current_trade_cycle_fails_closed_even_for_active_close(self) -> None:
        cycle = frozen_cycle(frozen=False)
        active_recipe = recipe(active=True)

        with pytest.raises(PositionManagementDecisionInvariantError):
            decide_position_management(active_recipe, cycle)

    def test_wrong_typed_recipe_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            decide_position_management("not-a-recipe", frozen_cycle())  # type: ignore[arg-type]

    def test_wrong_typed_current_trade_cycle_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            decide_position_management(recipe(), "not-a-cycle")  # type: ignore[arg-type]

    def test_resolve_effective_protection_fails_closed_when_unfrozen(self) -> None:
        cycle = frozen_cycle(frozen=False)

        with pytest.raises(PositionManagementDecisionInvariantError):
            resolve_effective_acknowledged_protection(cycle)
