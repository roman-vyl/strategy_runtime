from dataclasses import fields
from typing import cast

import pytest

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)


def desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100.00", "99.00", "103.00", "runner")


def applied_package(
    *,
    accepted_risk_multiplier: str = "+01.2500",
    calculated_quantity: str = "0.00100e3",
) -> AppliedEntryPackage:
    return AppliedEntryPackage(
        applied_desired_entry=desired_entry(),
        accepted_risk_multiplier=accepted_risk_multiplier,
        calculated_quantity=calculated_quantity,
    )


def test_applied_package_has_only_agreed_fields_and_preserves_decimal_lexemes() -> None:
    package = applied_package()

    assert tuple(field.name for field in fields(package)) == (
        "applied_desired_entry",
        "accepted_risk_multiplier",
        "calculated_quantity",
    )
    assert package.accepted_risk_multiplier == "+01.2500"
    assert package.calculated_quantity == "0.00100e3"


@pytest.mark.parametrize("value", [None, 1, "", "0", "-1", "NaN", " 1"])
def test_applied_package_rejects_invalid_accepted_risk(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        applied_package(accepted_risk_multiplier=cast("str", value))


@pytest.mark.parametrize("value", [None, 1, "", "NaN", " 1", "1 "])
def test_applied_package_rejects_invalid_quantity(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        applied_package(calculated_quantity=cast("str", value))


def test_current_cycle_has_only_minimal_i2_fields() -> None:
    cycle = CurrentTradeCycle(" cycle-owned-by-runtime ", applied_package())

    assert tuple(field.name for field in fields(cycle)) == (
        "trade_cycle_id",
        "applied_entry_package",
    )
    assert cycle.trade_cycle_id == " cycle-owned-by-runtime "
    assert not hasattr(cycle, "phase")
    assert not hasattr(cycle, "filled_quantity")
    assert not hasattr(cycle, "remaining_quantity")
    assert not hasattr(cycle, "average_entry_price")
    assert not hasattr(cycle, "fill_timestamp")
    assert not hasattr(cycle, "fill_ledger")
    assert not hasattr(cycle, "frozen_executed_entry_context")
    assert not hasattr(cycle, "position_management_recipe")


def test_current_cycle_accepts_absent_applied_package() -> None:
    assert CurrentTradeCycle("cycle-1", None).applied_entry_package is None


@pytest.mark.parametrize("value", [None, 1, ""])
def test_current_cycle_rejects_invalid_identity(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        CurrentTradeCycle(cast("str", value), None)


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
