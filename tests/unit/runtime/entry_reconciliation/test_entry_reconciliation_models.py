"""Tests for transport-free I3 reconciliation value models."""

from dataclasses import fields
from typing import cast

import pytest

from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    NoOp,
    Replace,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry


def desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100", "99", "103", "runner")


def test_decision_variants_have_exact_payload_shapes() -> None:
    entry = desired_entry()

    assert tuple(field.name for field in fields(NoOp())) == ()
    assert tuple(field.name for field in fields(Apply(entry))) == ("desired_entry",)
    assert tuple(field.name for field in fields(Replace("cycle-1", entry))) == (
        "trade_cycle_id",
        "desired_entry",
    )
    assert tuple(field.name for field in fields(Cancel("cycle-1"))) == ("trade_cycle_id",)


def test_command_has_only_i3_command_fields_and_preserves_domain_value() -> None:
    entry = desired_entry()
    command = EntryReconciliationCommand("instance", "cycle-1", "BTCUSDT.P", entry)

    assert tuple(field.name for field in fields(command)) == (
        "strategy_instance_id",
        "trade_cycle_id",
        "ticker",
        "desired_entry",
    )
    assert command.desired_entry == entry


def test_confirmation_variants_have_exact_fact_shapes() -> None:
    entry = desired_entry()
    applied = EntryAppliedConfirmation("instance", "cycle-1", entry, "0.00100e3")
    absent = EntryAbsentConfirmation("instance", "cycle-1")

    assert tuple(field.name for field in fields(applied)) == (
        "strategy_instance_id",
        "trade_cycle_id",
        "applied_desired_entry",
        "calculated_quantity",
    )
    assert tuple(field.name for field in fields(absent)) == (
        "strategy_instance_id",
        "trade_cycle_id",
    )
    assert applied.applied_desired_entry == entry
    assert applied.calculated_quantity == "0.00100e3"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Apply(cast("DesiredEntry", object())),
        lambda: Replace("cycle-1", cast("DesiredEntry", object())),
        lambda: EntryReconciliationCommand(
            "instance", "cycle-1", "BTCUSDT.P", cast("DesiredEntry", object())
        ),
        lambda: EntryAppliedConfirmation(
            "instance", "cycle-1", cast("DesiredEntry", object()), "1"
        ),
    ],
)
def test_models_reject_non_domain_desired_entry(factory) -> None:
    with pytest.raises(TypeError):
        factory()


@pytest.mark.parametrize("quantity", [None, 1, "", "NaN", " 1", "1 "])
def test_applied_confirmation_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        EntryAppliedConfirmation(
            "instance",
            "cycle-1",
            desired_entry(),
            cast("str", quantity),
        )


@pytest.mark.parametrize("identity", [None, 1, ""])
def test_i3_models_reject_invalid_identities(identity: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        Cancel(cast("str", identity))
    with pytest.raises((TypeError, ValueError)):
        EntryAbsentConfirmation("instance", cast("str", identity))
