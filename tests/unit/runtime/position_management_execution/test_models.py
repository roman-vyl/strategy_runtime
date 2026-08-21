"""Tests for transport-free position-management execution value models."""

from dataclasses import fields
from typing import cast

import pytest

from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.recipes.position_management import DesiredProtection


def protection() -> DesiredProtection:
    return DesiredProtection("99", "103")


def test_apply_protection_command_has_exact_minimal_fields() -> None:
    command = ApplyProtectionCommand("instance", "cycle-1", protection())

    assert tuple(field.name for field in fields(command)) == (
        "strategy_instance_id",
        "trade_cycle_id",
        "desired_protection",
    )
    assert command.desired_protection == protection()


def test_close_position_command_carries_canonical_exposure_fraction() -> None:
    command = ClosePositionCommand("instance", "cycle-1")

    assert tuple(field.name for field in fields(command)) == (
        "strategy_instance_id",
        "trade_cycle_id",
        "exposure_fraction",
    )
    assert command.exposure_fraction == "1"


@pytest.mark.parametrize("exposure_fraction", ["0.5", "0", "2", "-1", "1.0", "", "1 "])
def test_close_position_command_rejects_non_canonical_exposure_fraction(
    exposure_fraction: str,
) -> None:
    with pytest.raises(ValueError, match="exposure_fraction"):
        ClosePositionCommand("instance", "cycle-1", exposure_fraction=exposure_fraction)


def test_protection_applied_confirmation_has_exact_minimal_fields() -> None:
    confirmation = ProtectionAppliedConfirmation("instance", "cycle-1", protection())

    assert tuple(field.name for field in fields(confirmation)) == (
        "strategy_instance_id",
        "trade_cycle_id",
        "confirmed_protection",
    )
    assert confirmation.confirmed_protection == protection()


def test_position_closed_confirmation_carries_no_execution_lifecycle_field() -> None:
    confirmation = PositionClosedConfirmation("instance", "cycle-1")

    assert tuple(field.name for field in fields(confirmation)) == (
        "strategy_instance_id",
        "trade_cycle_id",
    )


@pytest.mark.parametrize("identity", [None, 1, ""])
def test_all_four_models_reject_invalid_identities(identity: object) -> None:
    bad_id = cast("str", identity)
    with pytest.raises((TypeError, ValueError)):
        ApplyProtectionCommand(bad_id, "cycle-1", protection())
    with pytest.raises((TypeError, ValueError)):
        ApplyProtectionCommand("instance", bad_id, protection())
    with pytest.raises((TypeError, ValueError)):
        ClosePositionCommand(bad_id, "cycle-1")
    with pytest.raises((TypeError, ValueError)):
        ClosePositionCommand("instance", bad_id)
    with pytest.raises((TypeError, ValueError)):
        ProtectionAppliedConfirmation(bad_id, "cycle-1", protection())
    with pytest.raises((TypeError, ValueError)):
        PositionClosedConfirmation("instance", bad_id)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ApplyProtectionCommand("instance", "cycle-1", cast("DesiredProtection", object())),
        lambda: ProtectionAppliedConfirmation(
            "instance", "cycle-1", cast("DesiredProtection", object())
        ),
    ],
)
def test_protection_fields_reject_non_domain_values(factory) -> None:
    with pytest.raises(TypeError):
        factory()
