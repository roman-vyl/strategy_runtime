"""Tests for transport-free position-management decision value models."""

from dataclasses import fields
from typing import cast

import pytest

from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
)
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection


def test_decision_variants_have_exact_payload_shapes() -> None:
    protection = DesiredProtection("99", "103")
    close_signal = CloseSignal(True)

    assert tuple(field.name for field in fields(NoOp())) == ()
    assert tuple(field.name for field in fields(ApplyProtection("cycle-1", protection))) == (
        "trade_cycle_id",
        "desired_protection",
    )
    assert tuple(field.name for field in fields(ClosePosition("cycle-1", close_signal))) == (
        "trade_cycle_id",
        "close_signal",
    )


def test_apply_protection_preserves_the_domain_value() -> None:
    protection = DesiredProtection("99", None)

    assert ApplyProtection("cycle-1", protection).desired_protection == protection


def test_close_position_preserves_the_close_signal() -> None:
    close_signal = CloseSignal(True, reason="stop_hunt", component_id="trailing", layer="l1")

    assert ClosePosition("cycle-1", close_signal).close_signal == close_signal


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ApplyProtection("cycle-1", cast("DesiredProtection", object())),
        lambda: ClosePosition("cycle-1", cast("CloseSignal", object())),
    ],
)
def test_models_reject_wrong_typed_payload(factory) -> None:
    with pytest.raises(TypeError):
        factory()


@pytest.mark.parametrize("identity", [None, 1, ""])
def test_models_reject_invalid_trade_cycle_id(identity: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ApplyProtection(cast("str", identity), DesiredProtection("99", "103"))
    with pytest.raises((TypeError, ValueError)):
        ClosePosition(cast("str", identity), CloseSignal(True))
