from dataclasses import replace
from typing import Literal, cast

import pytest

from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    NoOp,
    Replace,
)
from strategy_runtime.runtime.entry_reconciliation.reconciliation import (
    decide_entry_reconciliation,
    desired_entries_equivalent,
    get_acknowledged_desired_entry,
    touch_trigger_entry_reconciliation,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
)


def desired_entry(
    *,
    side: Literal["long", "short"] = "long",
    source_plan_bar_open_time_ms: int = 900,
    planned_entry_price: str = "100",
    initial_stop_price: str = "99",
    initial_take_price: str = "103",
    locked_exit_profile: str = "runner",
) -> DesiredEntry:
    return DesiredEntry(
        side,
        source_plan_bar_open_time_ms,
        planned_entry_price,
        initial_stop_price,
        initial_take_price,
        locked_exit_profile,
    )


def cycle(entry: DesiredEntry, *, trade_cycle_id: str = "cycle-1") -> CurrentTradeCycle:
    return CurrentTradeCycle(
        trade_cycle_id,
        AppliedEntryPackage(entry, "0.0100"),
    )


@pytest.mark.parametrize(
    ("new_entry", "current_cycle", "expected"),
    [
        (None, None, NoOp()),
        (desired_entry(), None, Apply(desired_entry())),
        (desired_entry(), cycle(desired_entry()), NoOp()),
        (
            desired_entry(planned_entry_price="101"),
            cycle(desired_entry()),
            Replace("cycle-1", desired_entry(planned_entry_price="101")),
        ),
        (None, cycle(desired_entry()), Cancel("cycle-1")),
    ],
)
def test_complete_reconciliation_table(
    new_entry: DesiredEntry | None,
    current_cycle: CurrentTradeCycle | None,
    expected: NoOp | Apply | Replace | Cancel,
) -> None:
    assert decide_entry_reconciliation(new_entry, current_cycle) == expected


def test_acknowledged_entry_helper_uses_required_nested_package() -> None:
    entry = desired_entry()

    assert get_acknowledged_desired_entry(None) is None
    assert get_acknowledged_desired_entry(cycle(entry)) == entry


@pytest.mark.parametrize(
    "changed",
    [
        desired_entry(side="short"),
        desired_entry(source_plan_bar_open_time_ms=901),
        desired_entry(planned_entry_price="101"),
        desired_entry(initial_stop_price="98"),
        desired_entry(initial_take_price="104"),
        desired_entry(locked_exit_profile="fixed"),
    ],
)
def test_every_desired_entry_field_participates_in_exact_equivalence(
    changed: DesiredEntry,
) -> None:
    original = desired_entry()

    assert not desired_entries_equivalent(original, changed)
    assert decide_entry_reconciliation(changed, cycle(original)) == Replace("cycle-1", changed)


def test_equivalence_uses_canonical_domain_value_without_tolerance() -> None:
    assert desired_entries_equivalent(
        desired_entry(planned_entry_price="0100.000"),
        desired_entry(planned_entry_price="100"),
    )
    assert not desired_entries_equivalent(
        desired_entry(planned_entry_price="100"),
        desired_entry(planned_entry_price="100.0000001"),
    )


def test_cycle_identity_does_not_change_equivalence_decision() -> None:
    entry = desired_entry()
    first = cycle(entry, trade_cycle_id="cycle-a")
    second = replace(first, trade_cycle_id="cycle-b")

    assert decide_entry_reconciliation(entry, first) == NoOp()
    assert decide_entry_reconciliation(entry, second) == NoOp()


def frozen_cycle(entry: DesiredEntry, *, trade_cycle_id: str = "cycle-1") -> CurrentTradeCycle:
    return replace(
        cycle(entry, trade_cycle_id=trade_cycle_id),
        frozen_entry_context=FrozenExecutedEntryContext(
            desired_entry=entry,
            first_fill_at_ms=1_000,
            entry_bar_open_time_ms=900,
        ),
    )


@pytest.mark.parametrize(
    "new_entry",
    [
        desired_entry(),
        desired_entry(planned_entry_price="101"),
        None,
    ],
)
def test_frozen_entry_context_fails_closed_before_any_decision(
    new_entry: DesiredEntry | None,
) -> None:
    original = desired_entry()

    with pytest.raises(EntryReconciliationInvariantError, match="frozen"):
        decide_entry_reconciliation(new_entry, frozen_cycle(original))


def test_invalid_current_cycle_type_fails_closed_before_frozen_check() -> None:
    with pytest.raises(TypeError, match="current_trade_cycle must be CurrentTradeCycle or None"):
        decide_entry_reconciliation(desired_entry(), cast("CurrentTradeCycle", object()))


@pytest.mark.parametrize(
    ("trade_cycle_id", "entry", "error"),
    [
        ("", desired_entry(), ValueError),
        (cast("str", None), desired_entry(), ValueError),
        ("cycle-1", cast("DesiredEntry", object()), TypeError),
    ],
)
def test_replace_is_a_validated_value(
    trade_cycle_id: str, entry: DesiredEntry, error: type[Exception]
) -> None:
    with pytest.raises(error):
        Replace(trade_cycle_id, entry)


def test_changed_desired_entry_carries_the_new_entry_unchanged() -> None:
    changed = desired_entry(planned_entry_price="101")

    decision = decide_entry_reconciliation(changed, cycle(desired_entry()))

    assert type(decision) is Replace
    assert decision.desired_entry is changed


TF = 300_000  # 5m
SIGNAL = 12 * 60 * 60_000  # 12:00 signal bar open


def held(*, trade_cycle_id: str = "cycle-1") -> CurrentTradeCycle:
    return cycle(desired_entry(source_plan_bar_open_time_ms=SIGNAL), trade_cycle_id=trade_cycle_id)


def touch(
    new_entry: DesiredEntry | None,
    current_cycle: CurrentTradeCycle | None,
    *,
    bar: int = SIGNAL,
    lifetime: int = 3,
    timeframe_ms: int = TF,
) -> object:
    return touch_trigger_entry_reconciliation(
        new_entry,
        current_cycle,
        current_bar_open_time_ms=bar,
        timeframe_ms=timeframe_ms,
        order_lifetime_bars=lifetime,
    )


@pytest.mark.parametrize(
    ("new_entry", "expected"),
    [(None, NoOp()), (desired_entry(), Apply(desired_entry()))],
)
def test_touch_trigger_without_a_cycle_applies_like_today(
    new_entry: DesiredEntry | None, expected: object
) -> None:
    assert touch(new_entry, None) == expected


@pytest.mark.parametrize("bar_offset", [1, 2, 3])
@pytest.mark.parametrize(
    "new_entry",
    [
        None,
        desired_entry(source_plan_bar_open_time_ms=SIGNAL),
        desired_entry(planned_entry_price="101", source_plan_bar_open_time_ms=SIGNAL + TF),
        desired_entry(side="short", source_plan_bar_open_time_ms=SIGNAL + 2 * TF),
    ],
)
def test_touch_trigger_holds_the_entry_before_expiry(
    bar_offset: int, new_entry: DesiredEntry | None
) -> None:
    # N=3, signal 12:00: bars opening 12:05, 12:10, 12:15 close before the 12:25 boundary.
    assert touch(new_entry, held(), bar=SIGNAL + bar_offset * TF) == NoOp()


def test_touch_trigger_cancels_at_expiry_without_a_signal() -> None:
    # Bar 12:20-12:25 closes at the boundary.
    assert touch(None, held(), bar=SIGNAL + 4 * TF) == Cancel("cycle-1")


def test_touch_trigger_replaces_at_expiry_with_a_fresh_signal() -> None:
    bar = SIGNAL + 4 * TF
    fresh = desired_entry(planned_entry_price="101", source_plan_bar_open_time_ms=bar)
    assert touch(fresh, held(), bar=bar) == Replace("cycle-1", fresh)


def test_touch_trigger_replaces_even_an_equal_plan_at_expiry() -> None:
    bar = SIGNAL + 4 * TF
    same_prices = desired_entry(source_plan_bar_open_time_ms=bar)
    assert touch(same_prices, held(), bar=bar) == Replace("cycle-1", same_prices)


def test_touch_trigger_cancels_at_expiry_with_a_stale_signal() -> None:
    bar = SIGNAL + 4 * TF
    stale = desired_entry(source_plan_bar_open_time_ms=bar - TF)
    assert touch(stale, held(), bar=bar) == Cancel("cycle-1")


def test_touch_trigger_zero_lifetime_is_one_bar() -> None:
    assert touch(None, held(), bar=SIGNAL + TF, lifetime=0) == Cancel("cycle-1")
    assert touch(None, held(), bar=SIGNAL, lifetime=0) == NoOp()


def test_touch_trigger_first_bar_after_skipped_bars_expires() -> None:
    bar = SIGNAL + 9 * TF
    assert touch(None, held(), bar=bar) == Cancel("cycle-1")
    fresh = desired_entry(source_plan_bar_open_time_ms=bar)
    assert touch(fresh, held(), bar=bar) == Replace("cycle-1", fresh)


def test_touch_trigger_lifetime_is_counted_from_the_held_plan_only() -> None:
    # Counted from a 12:15 signal the lifetime would end at 12:40; the held
    # 12:00 plan expires at 12:25.
    later = desired_entry(source_plan_bar_open_time_ms=SIGNAL + 3 * TF)
    assert touch(later, held(), bar=SIGNAL + 3 * TF) == NoOp()
    bar = SIGNAL + 4 * TF
    assert touch(None, held(), bar=bar) == Cancel("cycle-1")


@pytest.mark.parametrize(
    "new_entry",
    [
        desired_entry(),
        desired_entry(planned_entry_price="101"),
        None,
    ],
)
def test_touch_trigger_fails_closed_once_the_entry_context_is_frozen(
    new_entry: DesiredEntry | None,
) -> None:
    with pytest.raises(EntryReconciliationInvariantError, match="frozen"):
        touch(new_entry, frozen_cycle(desired_entry()), bar=SIGNAL + 10 * TF)


def test_touch_trigger_rejects_invalid_input_types() -> None:
    with pytest.raises(TypeError, match="new_desired_entry must be DesiredEntry or None"):
        touch(cast("DesiredEntry", object()), None)
    with pytest.raises(TypeError, match="current_trade_cycle must be CurrentTradeCycle or None"):
        touch(desired_entry(), cast("CurrentTradeCycle", object()))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"bar": -1}, "current_bar_open_time_ms"),
        ({"bar": cast("int", 1.0)}, "current_bar_open_time_ms"),
        ({"timeframe_ms": 0}, "timeframe_ms"),
        ({"lifetime": -1}, "order_lifetime_bars"),
        ({"lifetime": cast("int", True)}, "order_lifetime_bars"),
        ({"lifetime": cast("int", 3.0)}, "order_lifetime_bars"),
    ],
)
def test_touch_trigger_rejects_invalid_lifetime_inputs(
    kwargs: dict[str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        touch(None, held(), **kwargs)  # type: ignore[arg-type]
