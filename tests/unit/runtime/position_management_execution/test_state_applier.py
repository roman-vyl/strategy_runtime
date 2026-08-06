from dataclasses import replace
from typing import cast

import pytest

from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.position_management_execution.state_applier import (
    apply_position_management_confirmation,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)


def desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100", "99", "103", "runner")


def runtime_state(
    *,
    latest_confirmed_management_protection: DesiredProtection | None = None,
) -> StrategyInstanceRuntimeState:
    state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id="instance",
            strategy_id="strategy",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={},
            source_path="a.json",
        )
    )
    entry = desired_entry()
    return replace(
        state,
        current_trade_cycle=CurrentTradeCycle(
            "cycle-1",
            AppliedEntryPackage(entry, "0.01"),
            FrozenExecutedEntryContext(entry, first_fill_at_ms=950, entry_bar_open_time_ms=900),
            latest_confirmed_management_protection,
        ),
    )


def test_apply_protection_updates_confirmed_value_and_preserves_other_fields() -> None:
    state = runtime_state()
    snapshot = replace(state)
    protection = DesiredProtection("98", "103")

    result = apply_position_management_confirmation(
        state,
        ApplyProtection("cycle-1", protection),
        ApplyProtectionCommand("instance", "cycle-1", protection),
        ProtectionAppliedConfirmation("instance", "cycle-1", protection),
    )

    assert state == snapshot
    assert result.current_trade_cycle == replace(
        snapshot.current_trade_cycle,  # type: ignore[union-attr]
        latest_confirmed_management_protection=protection,
    )


def test_close_position_clears_the_current_cycle() -> None:
    state = runtime_state()
    snapshot = replace(state)

    result = apply_position_management_confirmation(
        state,
        ClosePosition("cycle-1", CloseSignal(True)),
        ClosePositionCommand("instance", "cycle-1"),
        PositionClosedConfirmation("instance", "cycle-1"),
    )

    assert state == snapshot
    assert result.current_trade_cycle is None


def test_wrong_confirmation_variant_fails_closed() -> None:
    state = runtime_state()
    snapshot = replace(state)
    protection = DesiredProtection("98", "103")

    with pytest.raises(PositionManagementExecutionInvariantError, match="ProtectionApplied"):
        apply_position_management_confirmation(
            state,
            ApplyProtection("cycle-1", protection),
            ApplyProtectionCommand("instance", "cycle-1", protection),
            PositionClosedConfirmation("instance", "cycle-1"),
        )
    assert state == snapshot

    with pytest.raises(PositionManagementExecutionInvariantError, match="PositionClosed"):
        apply_position_management_confirmation(
            state,
            ClosePosition("cycle-1", CloseSignal(True)),
            ClosePositionCommand("instance", "cycle-1"),
            ProtectionAppliedConfirmation("instance", "cycle-1", protection),
        )
    assert state == snapshot


@pytest.mark.parametrize(
    ("sent", "confirmation"),
    [
        (
            ApplyProtectionCommand("other", "cycle-1", DesiredProtection("98", "103")),
            ProtectionAppliedConfirmation("instance", "cycle-1", DesiredProtection("98", "103")),
        ),
        (
            ApplyProtectionCommand("instance", "cycle-1", DesiredProtection("98", "103")),
            ProtectionAppliedConfirmation("other", "cycle-1", DesiredProtection("98", "103")),
        ),
    ],
)
def test_strategy_instance_identity_mismatch_fails_closed(
    sent: ApplyProtectionCommand,
    confirmation: ProtectionAppliedConfirmation,
) -> None:
    state = runtime_state()
    snapshot = replace(state)

    with pytest.raises(PositionManagementExecutionInvariantError, match="strategy_instance_id"):
        apply_position_management_confirmation(
            state,
            ApplyProtection("cycle-1", DesiredProtection("98", "103")),
            sent,
            confirmation,
        )

    assert state == snapshot


@pytest.mark.parametrize(
    ("sent_cycle_id", "confirmed_cycle_id"),
    [
        ("stale", "stale"),
        ("cycle-1", "other"),
    ],
)
def test_apply_protection_rejects_every_trade_cycle_mismatch(
    sent_cycle_id: str,
    confirmed_cycle_id: str,
) -> None:
    state = runtime_state()
    snapshot = replace(state)
    protection = DesiredProtection("98", "103")

    with pytest.raises(PositionManagementExecutionInvariantError, match="trade_cycle_id"):
        apply_position_management_confirmation(
            state,
            ApplyProtection("cycle-1", protection),
            ApplyProtectionCommand("instance", sent_cycle_id, protection),
            ProtectionAppliedConfirmation("instance", confirmed_cycle_id, protection),
        )

    assert state == snapshot


@pytest.mark.parametrize(
    "confirmed_protection",
    [
        DesiredProtection("97", "103"),
        DesiredProtection("98", None),
        DesiredProtection("98", "104"),
    ],
)
def test_apply_protection_rejects_every_protection_value_mismatch(
    confirmed_protection: DesiredProtection,
) -> None:
    state = runtime_state()
    snapshot = replace(state)
    decided = DesiredProtection("98", "103")

    with pytest.raises(PositionManagementExecutionInvariantError, match="confirmed protection"):
        apply_position_management_confirmation(
            state,
            ApplyProtection("cycle-1", decided),
            ApplyProtectionCommand("instance", "cycle-1", decided),
            ProtectionAppliedConfirmation("instance", "cycle-1", confirmed_protection),
        )

    assert state == snapshot


def test_missing_current_trade_cycle_fails_closed() -> None:
    state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id="instance",
            strategy_id="strategy",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={},
            source_path="a.json",
        )
    )
    protection = DesiredProtection("98", "103")

    with pytest.raises(PositionManagementExecutionInvariantError, match="requires an acknowledged"):
        apply_position_management_confirmation(
            state,
            ApplyProtection("cycle-1", protection),
            ApplyProtectionCommand("instance", "cycle-1", protection),
            ProtectionAppliedConfirmation("instance", "cycle-1", protection),
        )


def test_applier_rejects_no_op_instead_of_returning_a_failure_result() -> None:
    state = runtime_state()
    protection = DesiredProtection("98", "103")

    with pytest.raises(
        PositionManagementExecutionInvariantError,
        match="requires APPLY_PROTECTION or CLOSE_POSITION",
    ):
        apply_position_management_confirmation(
            state,
            cast("ApplyProtection | ClosePosition", NoOp()),
            ApplyProtectionCommand("instance", "cycle-1", protection),
            ProtectionAppliedConfirmation("instance", "cycle-1", protection),
        )
