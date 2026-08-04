from dataclasses import replace
from typing import Literal

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
