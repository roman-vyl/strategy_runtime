from dataclasses import replace
from inspect import signature
from unittest.mock import patch

import pytest

from strategy_runtime.runtime.entry_reconciliation.command_builder import (
    build_entry_reconciliation_command,
)
from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryReconciliationCommand,
    NoOp,
    Replace,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)


def desired_entry(*, price: str = "100") -> DesiredEntry:
    return DesiredEntry("long", 900, price, "99", "103", "runner")


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
    state = runtime_state()
    snapshot = replace(state)

    assert build_entry_reconciliation_command(state, NoOp()) is None
    assert state == snapshot


def test_apply_builds_i3_command_with_caller_reserved_identity() -> None:
    state = runtime_state()
    entry = desired_entry()

    with patch(
        "strategy_runtime.runtime.state.identity.new_trade_cycle_id",
        side_effect=AssertionError("builder must not generate an identity"),
    ):
        result = build_entry_reconciliation_command(
            state,
            Apply(entry),
            apply_trade_cycle_id="cycle-new",
        )

    assert result == EntryReconciliationCommand(
        strategy_instance_id="instance",
        trade_cycle_id="cycle-new",
        ticker="BTCUSDT.P",
        desired_entry=entry,
    )
    assert state.current_trade_cycle is None


def test_replace_uses_only_decision_payload_and_current_state() -> None:
    state = runtime_state(with_cycle=True)
    entry = desired_entry(price="101")

    result = build_entry_reconciliation_command(
        state,
        Replace("cycle-1", entry),
    )

    assert result == EntryReconciliationCommand(
        strategy_instance_id="instance",
        trade_cycle_id="cycle-1",
        ticker="BTCUSDT.P",
        desired_entry=entry,
    )


def test_cancel_builds_explicit_absence_command() -> None:
    state = runtime_state(with_cycle=True)

    result = build_entry_reconciliation_command(state, Cancel("cycle-1"))

    assert result == EntryReconciliationCommand(
        strategy_instance_id="instance",
        trade_cycle_id="cycle-1",
        ticker="BTCUSDT.P",
        desired_entry=None,
    )


@pytest.mark.parametrize(
    ("state", "decision", "apply_id", "message"),
    [
        (runtime_state(), NoOp(), "cycle-new", "NO_OP prohibits"),
        (runtime_state(), Apply(desired_entry()), None, "APPLY requires a non-empty"),
        (runtime_state(), Apply(desired_entry()), "", "APPLY requires a non-empty"),
        (
            runtime_state(with_cycle=True),
            Apply(desired_entry()),
            "cycle-new",
            "APPLY requires no current",
        ),
        (
            runtime_state(with_cycle=True),
            Replace("cycle-1", desired_entry()),
            "cycle-new",
            "only APPLY accepts",
        ),
        (
            runtime_state(with_cycle=True),
            Cancel("cycle-1"),
            "cycle-new",
            "only APPLY accepts",
        ),
        (
            runtime_state(),
            Replace("cycle-1", desired_entry()),
            None,
            "REPLACE requires an acknowledged",
        ),
        (
            runtime_state(),
            Cancel("cycle-1"),
            None,
            "CANCEL requires an acknowledged",
        ),
        (
            runtime_state(with_cycle=True),
            Replace("stale", desired_entry()),
            None,
            "does not match current",
        ),
        (
            runtime_state(with_cycle=True),
            Cancel("stale"),
            None,
            "does not match current",
        ),
    ],
)
def test_incoherent_builder_inputs_fail_closed_without_state_mutation(
    state: StrategyInstanceRuntimeState,
    decision: NoOp | Apply | Replace | Cancel,
    apply_id: str | None,
    message: str,
) -> None:
    snapshot = replace(state)

    with pytest.raises(EntryReconciliationInvariantError, match=message):
        build_entry_reconciliation_command(state, decision, apply_id)

    assert state == snapshot


def test_builder_signature_contains_no_duplicate_reconciliation_inputs() -> None:
    assert tuple(signature(build_entry_reconciliation_command).parameters) == (
        "state",
        "decision",
        "apply_trade_cycle_id",
    )
