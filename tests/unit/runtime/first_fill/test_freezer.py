"""FirstFillFreezer: the single owner of the entry-order lifetime policy at the freeze."""

import ast
from pathlib import Path

import pytest

from strategy_runtime.runtime.first_fill.freezer import FirstFillFreezer
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)

_T0 = 1_785_000_000_000
_M5 = 300_000


def _state() -> StrategyInstanceRuntimeState:
    entry = DesiredEntry("long", _T0, "100", "99", "103", "runner")
    return StrategyInstanceRuntimeState(
        strategy_instance_id="instance",
        strategy_id="strategy",
        registered_spec_snapshot=RegisteredSpecSnapshot(
            instrument="BTCUSDT.P", base_timeframe="5m", raw_spec={}, source_path="a.json"
        ),
        risk_multiplier="1",
        current_trade_cycle=CurrentTradeCycle("cycle-1", AppliedEntryPackage(entry, "0.01")),
    )


def _boundary(state: StrategyInstanceRuntimeState) -> int | None:
    cycle = state.current_trade_cycle
    assert cycle is not None and cycle.frozen_entry_context is not None
    return cycle.frozen_entry_context.entry_order_expires_at_bar


def test_touch_trigger_freezes_the_boundary() -> None:
    freezer = FirstFillFreezer(live_entry_mode="touch_trigger", order_lifetime_bars=3)

    assert _boundary(freezer.freeze(_state(), "cycle-1", _T0 + 1_000)) == _T0 + 5 * _M5


def test_ema_anchor_ignores_any_lifetime() -> None:
    freezer = FirstFillFreezer(live_entry_mode="ema_anchor", order_lifetime_bars=3)

    assert _boundary(freezer.freeze(_state(), "cycle-1", _T0 + 1_000)) is None
    assert _boundary(FirstFillFreezer().freeze(_state(), "cycle-1", _T0 + 1_000)) is None


def test_an_already_frozen_cycle_keeps_its_boundary_under_another_policy() -> None:
    frozen = FirstFillFreezer(live_entry_mode="touch_trigger", order_lifetime_bars=3).freeze(
        _state(), "cycle-1", _T0 + 1_000
    )

    later = FirstFillFreezer(live_entry_mode="touch_trigger", order_lifetime_bars=9)

    assert later.freeze(frozen, "cycle-1", _T0 + 1_000) is frozen


@pytest.mark.parametrize("lifetime", [None, -1, 1.5])
def test_touch_trigger_requires_a_lifetime(lifetime: object) -> None:
    with pytest.raises(ValueError):
        FirstFillFreezer(live_entry_mode="touch_trigger", order_lifetime_bars=lifetime)  # type: ignore[arg-type]


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        FirstFillFreezer(live_entry_mode="other")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path",
    [
        "src/strategy_runtime/runtime/orchestrator/orchestrator.py",
        "src/strategy_runtime/runtime/abi_execution_event/orchestrator.py",
        "src/strategy_runtime/runtime/operator_commands/service.py",
        "src/strategy_runtime/runtime/uncertain_exchange_state_resolver/resolver.py",
    ],
)
def test_first_fill_handlers_freeze_only_through_the_freezer(path: str) -> None:
    source = Path(path).read_text(encoding="utf-8")
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name | ast.Attribute)
    }
    assert "apply_first_fill" not in names
    assert "order_lifetime_bars" not in source
