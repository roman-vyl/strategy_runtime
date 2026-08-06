from dataclasses import replace
from inspect import signature

import pytest

from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
    NoOp,
)
from strategy_runtime.runtime.position_management_execution.command_builder import (
    build_position_management_command,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)


def desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100", "99", "103", "runner")


def runtime_state(*, with_cycle: bool = False) -> StrategyInstanceRuntimeState:
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
    if not with_cycle:
        return state
    return replace(
        state,
        current_trade_cycle=CurrentTradeCycle(
            "cycle-1",
            AppliedEntryPackage(desired_entry(), "0.01"),
        ),
    )


def test_no_op_returns_no_command_and_preserves_state_value() -> None:
    state = runtime_state(with_cycle=True)
    snapshot = replace(state)

    assert build_position_management_command(state, NoOp()) is None
    assert state == snapshot


def test_apply_protection_builds_command_from_state_and_decision() -> None:
    state = runtime_state(with_cycle=True)
    protection = DesiredProtection("98", "103")

    result = build_position_management_command(state, ApplyProtection("cycle-1", protection))

    assert result == ApplyProtectionCommand(
        strategy_instance_id="instance",
        trade_cycle_id="cycle-1",
        desired_protection=protection,
    )


def test_close_position_builds_command_carrying_no_quantity() -> None:
    state = runtime_state(with_cycle=True)

    result = build_position_management_command(
        state,
        ClosePosition("cycle-1", CloseSignal(True, reason="stop_hunt")),
    )

    assert result == ClosePositionCommand(
        strategy_instance_id="instance",
        trade_cycle_id="cycle-1",
    )


@pytest.mark.parametrize(
    ("state", "decision", "message"),
    [
        (
            runtime_state(),
            ApplyProtection("cycle-1", DesiredProtection("98", "103")),
            "requires an acknowledged",
        ),
        (
            runtime_state(),
            ClosePosition("cycle-1", CloseSignal(True)),
            "requires an acknowledged",
        ),
        (
            runtime_state(with_cycle=True),
            ApplyProtection("stale", DesiredProtection("98", "103")),
            "does not match current",
        ),
        (
            runtime_state(with_cycle=True),
            ClosePosition("stale", CloseSignal(True)),
            "does not match current",
        ),
    ],
)
def test_incoherent_builder_inputs_fail_closed_without_state_mutation(
    state: StrategyInstanceRuntimeState,
    decision: ApplyProtection | ClosePosition,
    message: str,
) -> None:
    snapshot = replace(state)

    with pytest.raises(PositionManagementExecutionInvariantError, match=message):
        build_position_management_command(state, decision)

    assert state == snapshot


def test_builder_signature_contains_no_extra_inputs() -> None:
    assert tuple(signature(build_position_management_command).parameters) == (
        "state",
        "decision",
    )
