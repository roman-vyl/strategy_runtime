from dataclasses import fields
from typing import cast

import pytest

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)


def desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100.00", "99.00", "103.00", "runner")


def applied_package(
    *,
    calculated_quantity: str = "0.00100e3",
) -> AppliedEntryPackage:
    return AppliedEntryPackage(
        applied_desired_entry=desired_entry(),
        calculated_quantity=calculated_quantity,
    )


def test_applied_package_has_only_agreed_fields_and_preserves_decimal_lexemes() -> None:
    package = applied_package()

    assert tuple(field.name for field in fields(package)) == (
        "applied_desired_entry",
        "calculated_quantity",
    )
    assert package.calculated_quantity == "0.00100e3"


def test_applied_package_rejects_invalid_desired_entry() -> None:
    with pytest.raises(TypeError, match="applied_desired_entry must be DesiredEntry"):
        AppliedEntryPackage(
            applied_desired_entry=cast("DesiredEntry", object()),
            calculated_quantity="1",
        )


@pytest.mark.parametrize("value", [None, 1, "", "NaN", " 1", "1 "])
def test_applied_package_rejects_invalid_quantity(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        applied_package(calculated_quantity=cast("str", value))


def test_current_cycle_has_only_minimal_i2_fields_plus_frozen_context() -> None:
    cycle = CurrentTradeCycle(" cycle-owned-by-runtime ", applied_package())

    assert tuple(field.name for field in fields(cycle)) == (
        "trade_cycle_id",
        "applied_entry_package",
        "frozen_entry_context",
        "latest_confirmed_management_protection",
    )
    assert cycle.trade_cycle_id == " cycle-owned-by-runtime "
    assert cycle.frozen_entry_context is None
    assert cycle.latest_confirmed_management_protection is None
    assert not hasattr(cycle, "phase")
    assert not hasattr(cycle, "filled_quantity")
    assert not hasattr(cycle, "remaining_quantity")
    assert not hasattr(cycle, "average_entry_price")
    assert not hasattr(cycle, "fill_timestamp")
    assert not hasattr(cycle, "fill_ledger")
    assert not hasattr(cycle, "position_management_recipe")
    assert not hasattr(cycle, "diagnostics")


def test_current_cycle_accepts_and_rejects_latest_confirmed_management_protection() -> None:
    protection = DesiredProtection("99", "103")
    cycle = CurrentTradeCycle(
        "cycle-1", applied_package(), latest_confirmed_management_protection=protection
    )

    assert cycle.latest_confirmed_management_protection is protection

    with pytest.raises(TypeError, match="latest_confirmed_management_protection must be"):
        CurrentTradeCycle(
            "cycle-1",
            applied_package(),
            latest_confirmed_management_protection=cast("DesiredProtection", 1),
        )


def frozen_context(
    *,
    entry: DesiredEntry | None = None,
    first_fill_at_ms: int = 1_000,
    entry_bar_open_time_ms: int = 900,
) -> FrozenExecutedEntryContext:
    return FrozenExecutedEntryContext(
        desired_entry=entry if entry is not None else desired_entry(),
        first_fill_at_ms=first_fill_at_ms,
        entry_bar_open_time_ms=entry_bar_open_time_ms,
    )


def test_frozen_context_has_only_three_agreed_fields() -> None:
    context = frozen_context()

    assert tuple(field.name for field in fields(context)) == (
        "desired_entry",
        "first_fill_at_ms",
        "entry_bar_open_time_ms",
    )
    assert not hasattr(context, "average_entry_price")
    assert not hasattr(context, "filled_quantity")
    assert not hasattr(context, "remaining_quantity")
    assert not hasattr(context, "phase")


def test_frozen_context_rejects_invalid_desired_entry() -> None:
    with pytest.raises(TypeError, match="desired_entry must be DesiredEntry"):
        FrozenExecutedEntryContext(
            desired_entry=cast("DesiredEntry", object()),
            first_fill_at_ms=1_000,
            entry_bar_open_time_ms=900,
        )


@pytest.mark.parametrize("value", [0, -1, "1000", True, 1.0, None])
def test_frozen_context_rejects_invalid_first_fill_at_ms(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        FrozenExecutedEntryContext(
            desired_entry=desired_entry(),
            first_fill_at_ms=cast("int", value),
            entry_bar_open_time_ms=900,
        )


@pytest.mark.parametrize("value", [-1, "900", True, 1.0, None])
def test_frozen_context_rejects_invalid_entry_bar_open_time_ms(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        FrozenExecutedEntryContext(
            desired_entry=desired_entry(),
            first_fill_at_ms=1_000,
            entry_bar_open_time_ms=cast("int", value),
        )


def test_frozen_context_rejects_entry_bar_after_first_fill() -> None:
    with pytest.raises(ValueError, match="must not be after"):
        FrozenExecutedEntryContext(
            desired_entry=desired_entry(),
            first_fill_at_ms=1_000,
            entry_bar_open_time_ms=1_001,
        )


def test_current_cycle_accepts_and_rejects_frozen_context() -> None:
    context = frozen_context()
    cycle = CurrentTradeCycle("cycle-1", applied_package(), context)

    assert cycle.frozen_entry_context is context

    with pytest.raises(TypeError, match="frozen_entry_context must be"):
        CurrentTradeCycle("cycle-1", applied_package(), cast("FrozenExecutedEntryContext", 1))


@pytest.mark.parametrize("value", [None, 1, ""])
def test_current_cycle_rejects_invalid_applied_package(value: object) -> None:
    with pytest.raises(TypeError, match="applied_entry_package must be AppliedEntryPackage"):
        CurrentTradeCycle("cycle-1", cast("AppliedEntryPackage", value))


@pytest.mark.parametrize("value", [None, 1, ""])
def test_current_cycle_rejects_invalid_identity(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        CurrentTradeCycle(cast("str", value), applied_package())


def test_strategy_state_requires_and_preserves_exact_risk() -> None:
    state = StrategyInstanceRuntimeState(
        strategy_instance_id="instance",
        strategy_id="strategy",
        registered_spec_snapshot=RegisteredSpecSnapshot(
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={},
            source_path="a.json",
        ),
        risk_multiplier="+01.2500",
    )

    assert state.risk_multiplier == "+01.2500"
    assert state.current_trade_cycle is None
    assert "risk_multiplier" not in state.registered_spec_snapshot.raw_spec


@pytest.mark.parametrize("value", [None, "0", "-1", "NaN", " 1", "1 "])
def test_strategy_state_rejects_invalid_risk(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        StrategyInstanceRuntimeState(
            strategy_instance_id="instance",
            strategy_id="strategy",
            registered_spec_snapshot=RegisteredSpecSnapshot("BTCUSDT.P", "5m", {}, "a.json"),
            risk_multiplier=cast("str", value),
        )


def test_strategy_state_has_no_risk_constructor_default() -> None:
    snapshot = RegisteredSpecSnapshot("BTCUSDT.P", "5m", {}, "a.json")
    with pytest.raises(TypeError):
        StrategyInstanceRuntimeState(  # type: ignore[call-arg]
            strategy_instance_id="instance",
            strategy_id="strategy",
            registered_spec_snapshot=snapshot,
        )


def test_registration_request_contains_no_risk_multiplier() -> None:
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id="instance",
        strategy_id="strategy",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={},
        source_path="a.json",
    )

    assert tuple(field.name for field in fields(request)) == (
        "strategy_instance_id",
        "strategy_id",
        "instrument",
        "base_timeframe",
        "raw_spec",
        "source_path",
    )
    assert not hasattr(request, "risk_multiplier")

    with pytest.raises(TypeError):
        GetOrCreateStrategyInstanceRuntimeStateRequest(  # type: ignore[call-arg]
            strategy_instance_id="instance",
            strategy_id="strategy",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            risk_multiplier="1",
            raw_spec={},
            source_path="a.json",
        )
