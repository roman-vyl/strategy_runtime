from typing import Any

import pytest

from strategy_runtime.runtime.recipes.entry import DesiredEntry


def make_desired_entry(*, initial_take_price: Any = "103") -> DesiredEntry:
    return DesiredEntry(
        side="long",
        source_plan_bar_open_time_ms=900,
        planned_entry_price="100",
        initial_stop_price="99",
        initial_take_price=initial_take_price,
        locked_exit_profile="runner",
    )


def test_desired_entry_requires_and_normalizes_positive_initial_take() -> None:
    result = make_desired_entry(initial_take_price="00103.2500")

    assert result.initial_take_price == "103.25"


@pytest.mark.parametrize(
    "invalid_take",
    [None, "", " ", "not-a-decimal", "NaN", "Infinity", "0", "-0", "-1", 103],
)
def test_desired_entry_rejects_invalid_initial_take(invalid_take: Any) -> None:
    with pytest.raises(ValueError):
        make_desired_entry(initial_take_price=invalid_take)


def test_desired_entry_rejects_missing_initial_take() -> None:
    with pytest.raises(TypeError, match="initial_take_price"):
        DesiredEntry(  # type: ignore[call-arg]
            side="long",
            source_plan_bar_open_time_ms=900,
            planned_entry_price="100",
            initial_stop_price="99",
            locked_exit_profile="runner",
        )


def test_desired_entry_rejects_unknown_side() -> None:
    with pytest.raises(ValueError, match="side must be long or short"):
        DesiredEntry(
            side="both",  # type: ignore[arg-type]
            source_plan_bar_open_time_ms=900,
            planned_entry_price="100",
            initial_stop_price="99",
            initial_take_price="103",
            locked_exit_profile="runner",
        )
