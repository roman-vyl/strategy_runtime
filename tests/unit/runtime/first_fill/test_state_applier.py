from dataclasses import replace
from typing import cast

import pytest

from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.first_fill.state_applier import apply_first_fill
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)

TRADE_CYCLE_ID = "cycle-1"
SOURCE_PLAN_BAR_OPEN_TIME_MS = 900_000


def desired_entry(
    *, source_plan_bar_open_time_ms: int = SOURCE_PLAN_BAR_OPEN_TIME_MS
) -> DesiredEntry:
    return DesiredEntry(
        "long",
        source_plan_bar_open_time_ms,
        "100",
        "99",
        "103",
        "runner",
    )


def runtime_state(
    *,
    base_timeframe: str = "15m",
    trade_cycle_id: str | None = TRADE_CYCLE_ID,
    entry: DesiredEntry | None = None,
    frozen_entry_context: object = None,
) -> StrategyInstanceRuntimeState:
    current_trade_cycle = None
    if trade_cycle_id is not None:
        current_trade_cycle = CurrentTradeCycle(
            trade_cycle_id,
            AppliedEntryPackage(entry if entry is not None else desired_entry(), "0.01"),
            frozen_entry_context,  # type: ignore[arg-type]
        )
    return StrategyInstanceRuntimeState(
        strategy_instance_id="instance",
        strategy_id="strategy",
        registered_spec_snapshot=RegisteredSpecSnapshot(
            instrument="BTCUSDT.P",
            base_timeframe=base_timeframe,
            raw_spec={},
            source_path="a.json",
        ),
        risk_multiplier="1",
        current_trade_cycle=current_trade_cycle,
    )


def test_first_fill_freezes_context_with_applied_entry_and_aligned_bar() -> None:
    state = runtime_state()

    result = apply_first_fill(state, TRADE_CYCLE_ID, 905_000)

    assert result.current_trade_cycle is not None
    context = result.current_trade_cycle.frozen_entry_context
    assert context is not None
    applied_entry = state.current_trade_cycle.applied_entry_package.applied_desired_entry  # type: ignore[union-attr]
    assert context.desired_entry is applied_entry
    assert context.first_fill_at_ms == 905_000
    assert context.entry_bar_open_time_ms == 900_000


def test_alignment_reads_base_timeframe_from_registered_spec_snapshot() -> None:
    fine = apply_first_fill(runtime_state(base_timeframe="1m"), TRADE_CYCLE_ID, 960_000)
    coarse = apply_first_fill(runtime_state(base_timeframe="15m"), TRADE_CYCLE_ID, 960_000)

    assert fine.current_trade_cycle.frozen_entry_context.entry_bar_open_time_ms == 960_000  # type: ignore[union-attr]
    assert coarse.current_trade_cycle.frozen_entry_context.entry_bar_open_time_ms == 900_000  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "state",
    [
        cast("StrategyInstanceRuntimeState", object()),
        runtime_state(trade_cycle_id=None),
    ],
)
def test_wrong_type_or_no_current_cycle_fails_closed(
    state: StrategyInstanceRuntimeState,
) -> None:
    with pytest.raises(FirstFillInvariantError):
        apply_first_fill(state, TRADE_CYCLE_ID, 905_000)


def test_mismatched_trade_cycle_id_fails_closed() -> None:
    state = runtime_state(trade_cycle_id="other-cycle")

    with pytest.raises(FirstFillInvariantError, match="trade_cycle_id"):
        apply_first_fill(state, TRADE_CYCLE_ID, 905_000)


def test_unsupported_base_timeframe_propagates_value_error_unwrapped() -> None:
    state = runtime_state(base_timeframe="unsupported")

    with pytest.raises(ValueError, match="unsupported base_timeframe"):
        apply_first_fill(state, TRADE_CYCLE_ID, 905_000)


def test_retry_with_identical_timestamp_is_a_no_op_returning_same_object() -> None:
    frozen = apply_first_fill(runtime_state(), TRADE_CYCLE_ID, 905_000)

    retried = apply_first_fill(frozen, TRADE_CYCLE_ID, 905_000)

    assert retried is frozen


def test_retry_with_different_timestamp_fails_closed_and_preserves_original() -> None:
    frozen = apply_first_fill(runtime_state(), TRADE_CYCLE_ID, 905_000)
    original_context = frozen.current_trade_cycle.frozen_entry_context  # type: ignore[union-attr]

    with pytest.raises(FirstFillInvariantError, match="already frozen"):
        apply_first_fill(frozen, TRADE_CYCLE_ID, 906_000)

    assert frozen.current_trade_cycle.frozen_entry_context is original_context  # type: ignore[union-attr]


def test_frozen_desired_entry_is_exactly_the_applied_desired_entry() -> None:
    state = runtime_state()
    applied = state.current_trade_cycle.applied_entry_package.applied_desired_entry  # type: ignore[union-attr]

    result = apply_first_fill(state, TRADE_CYCLE_ID, 905_000)

    assert result.current_trade_cycle.frozen_entry_context.desired_entry is applied  # type: ignore[union-attr]


def test_successful_call_does_not_mutate_input_state() -> None:
    state = runtime_state()
    snapshot = replace(state)

    apply_first_fill(state, TRADE_CYCLE_ID, 905_000)

    assert state == snapshot
    assert state.current_trade_cycle.frozen_entry_context is None  # type: ignore[union-attr]


def test_entry_bar_before_desired_entry_source_plan_bar_fails_closed() -> None:
    entry = desired_entry(source_plan_bar_open_time_ms=900_000)
    state = runtime_state(base_timeframe="15m", entry=entry)

    with pytest.raises(FirstFillInvariantError, match="precedes"):
        apply_first_fill(state, TRADE_CYCLE_ID, 899_999)

    assert state.current_trade_cycle.frozen_entry_context is None  # type: ignore[union-attr]
