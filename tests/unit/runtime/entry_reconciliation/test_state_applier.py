from dataclasses import replace
from typing import Literal, cast

import pytest

from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    NoOp,
    Replace,
)
from strategy_runtime.runtime.entry_reconciliation.state_applier import (
    apply_success_confirmation,
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


def runtime_state(*, applied_entry: DesiredEntry | None = None) -> StrategyInstanceRuntimeState:
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
    if applied_entry is None:
        return state
    return replace(
        state,
        current_trade_cycle=CurrentTradeCycle(
            "cycle-1",
            AppliedEntryPackage(applied_entry, "0.01"),
        ),
    )


def command(
    *,
    trade_cycle_id: str,
    entry: DesiredEntry | None,
    strategy_instance_id: str = "instance",
    ticker: str = "BTCUSDT.P",
) -> EntryReconciliationCommand:
    return EntryReconciliationCommand(
        strategy_instance_id,
        trade_cycle_id,
        ticker,
        entry,
    )


def applied_confirmation(
    *,
    trade_cycle_id: str,
    entry: DesiredEntry,
    strategy_instance_id: str = "instance",
    quantity: str = "0.00100e3",
) -> EntryAppliedConfirmation:
    return EntryAppliedConfirmation(
        strategy_instance_id,
        trade_cycle_id,
        entry,
        quantity,
    )


def test_apply_creates_complete_cycle_only_after_matching_confirmation() -> None:
    state = runtime_state()
    snapshot = replace(state)
    entry = desired_entry()
    sent = command(trade_cycle_id="cycle-new", entry=entry)

    result = apply_success_confirmation(
        state,
        Apply(entry),
        sent,
        applied_confirmation(trade_cycle_id="cycle-new", entry=entry),
    )

    assert state == snapshot
    assert state.current_trade_cycle is None
    assert result.current_trade_cycle == CurrentTradeCycle(
        "cycle-new",
        AppliedEntryPackage(entry, "0.00100e3"),
    )


def test_replace_preserves_cycle_identity_and_atomically_replaces_package() -> None:
    original = desired_entry()
    updated = desired_entry(planned_entry_price="101")
    state = runtime_state(applied_entry=original)
    snapshot = replace(state)

    result = apply_success_confirmation(
        state,
        Replace("cycle-1", updated),
        command(trade_cycle_id="cycle-1", entry=updated),
        applied_confirmation(trade_cycle_id="cycle-1", entry=updated, quantity="2.5000"),
    )

    assert state == snapshot
    assert result.current_trade_cycle == CurrentTradeCycle(
        "cycle-1",
        AppliedEntryPackage(updated, "2.5000"),
    )


def test_cancel_clears_complete_cycle() -> None:
    state = runtime_state(applied_entry=desired_entry())

    result = apply_success_confirmation(
        state,
        Cancel("cycle-1"),
        command(trade_cycle_id="cycle-1", entry=None),
        EntryAbsentConfirmation("instance", "cycle-1"),
    )

    assert result.current_trade_cycle is None


@pytest.mark.parametrize(
    ("decision", "confirmation"),
    [
        (
            Apply(desired_entry()),
            EntryAbsentConfirmation("instance", "cycle-new"),
        ),
        (
            Replace("cycle-1", desired_entry(planned_entry_price="101")),
            EntryAbsentConfirmation("instance", "cycle-1"),
        ),
        (
            Cancel("cycle-1"),
            applied_confirmation(trade_cycle_id="cycle-1", entry=desired_entry()),
        ),
    ],
)
def test_wrong_success_variant_fails_closed(
    decision: Apply | Replace | Cancel,
    confirmation: EntryAppliedConfirmation | EntryAbsentConfirmation,
) -> None:
    entry = getattr(decision, "desired_entry", None)
    state = (
        runtime_state()
        if isinstance(decision, Apply)
        else runtime_state(applied_entry=desired_entry())
    )
    cycle_id = "cycle-new" if isinstance(decision, Apply) else "cycle-1"
    snapshot = replace(state)

    with pytest.raises(EntryReconciliationInvariantError):
        apply_success_confirmation(
            state,
            decision,
            command(trade_cycle_id=cycle_id, entry=entry),
            confirmation,
        )

    assert state == snapshot


def test_cancel_rejects_sent_present_desired_entry_even_after_absent_confirmation() -> None:
    state = runtime_state(applied_entry=desired_entry())
    snapshot = replace(state)

    with pytest.raises(
        EntryReconciliationInvariantError,
        match="CANCEL requires sent command desired_entry to be null",
    ):
        apply_success_confirmation(
            state,
            Cancel("cycle-1"),
            command(trade_cycle_id="cycle-1", entry=desired_entry()),
            EntryAbsentConfirmation("instance", "cycle-1"),
        )

    assert state == snapshot


@pytest.mark.parametrize(
    ("sent", "confirmation", "message"),
    [
        (
            command(
                strategy_instance_id="other",
                trade_cycle_id="cycle-new",
                entry=desired_entry(),
            ),
            applied_confirmation(trade_cycle_id="cycle-new", entry=desired_entry()),
            "sent command strategy_instance_id",
        ),
        (
            command(trade_cycle_id="cycle-new", entry=desired_entry()),
            applied_confirmation(
                strategy_instance_id="other",
                trade_cycle_id="cycle-new",
                entry=desired_entry(),
            ),
            "confirmation strategy_instance_id",
        ),
        (
            command(
                ticker="ETHUSDT.P",
                trade_cycle_id="cycle-new",
                entry=desired_entry(),
            ),
            applied_confirmation(trade_cycle_id="cycle-new", entry=desired_entry()),
            "sent command ticker",
        ),
        (
            command(trade_cycle_id="cycle-new", entry=desired_entry()),
            applied_confirmation(trade_cycle_id="other", entry=desired_entry()),
            "trade_cycle_id does not match",
        ),
    ],
)
def test_apply_rejects_ownership_and_identity_mismatch(
    sent: EntryReconciliationCommand,
    confirmation: EntryAppliedConfirmation,
    message: str,
) -> None:
    state = runtime_state()
    snapshot = replace(state)

    with pytest.raises(EntryReconciliationInvariantError, match=message):
        apply_success_confirmation(state, Apply(desired_entry()), sent, confirmation)

    assert state == snapshot


@pytest.mark.parametrize(
    ("decision", "sent_cycle_id", "confirmed_cycle_id"),
    [
        (Replace("stale", desired_entry(planned_entry_price="101")), "stale", "stale"),
        (
            Replace("cycle-1", desired_entry(planned_entry_price="101")),
            "other",
            "other",
        ),
        (
            Replace("cycle-1", desired_entry(planned_entry_price="101")),
            "cycle-1",
            "other",
        ),
        (Cancel("stale"), "stale", "stale"),
        (Cancel("cycle-1"), "other", "other"),
        (Cancel("cycle-1"), "cycle-1", "other"),
    ],
)
def test_replace_and_cancel_reject_every_target_cycle_mismatch(
    decision: Replace | Cancel,
    sent_cycle_id: str,
    confirmed_cycle_id: str,
) -> None:
    original = desired_entry()
    updated = getattr(decision, "desired_entry", None)
    sent_entry = updated if isinstance(decision, Replace) else None
    confirmation = (
        applied_confirmation(
            trade_cycle_id=confirmed_cycle_id,
            entry=cast("DesiredEntry", updated),
        )
        if isinstance(decision, Replace)
        else EntryAbsentConfirmation("instance", confirmed_cycle_id)
    )
    state = runtime_state(applied_entry=original)
    snapshot = replace(state)

    with pytest.raises(EntryReconciliationInvariantError, match="trade_cycle_id"):
        apply_success_confirmation(
            state,
            decision,
            command(trade_cycle_id=sent_cycle_id, entry=sent_entry),
            confirmation,
        )

    assert state == snapshot


@pytest.mark.parametrize(
    "confirmed_entry",
    [
        desired_entry(side="short"),
        desired_entry(source_plan_bar_open_time_ms=901),
        desired_entry(planned_entry_price="101"),
        desired_entry(initial_stop_price="98"),
        desired_entry(initial_take_price="104"),
        desired_entry(locked_exit_profile="fixed"),
    ],
)
def test_applied_confirmation_rejects_every_desired_entry_mismatch(
    confirmed_entry: DesiredEntry,
) -> None:
    expected = desired_entry()
    state = runtime_state()
    snapshot = replace(state)

    with pytest.raises(EntryReconciliationInvariantError, match="desired entry"):
        apply_success_confirmation(
            state,
            Apply(expected),
            command(trade_cycle_id="cycle-new", entry=expected),
            applied_confirmation(trade_cycle_id="cycle-new", entry=confirmed_entry),
        )

    assert state == snapshot


def test_applier_rejects_invalid_forged_confirmation_quantity() -> None:
    entry = desired_entry()
    state = runtime_state()
    snapshot = replace(state)
    invalid = object.__new__(EntryAppliedConfirmation)
    object.__setattr__(invalid, "strategy_instance_id", "instance")
    object.__setattr__(invalid, "trade_cycle_id", "cycle-new")
    object.__setattr__(invalid, "applied_desired_entry", entry)
    object.__setattr__(invalid, "calculated_quantity", "NaN")

    with pytest.raises(EntryReconciliationInvariantError, match="calculated_quantity"):
        apply_success_confirmation(
            state,
            Apply(entry),
            command(trade_cycle_id="cycle-new", entry=entry),
            invalid,
        )

    assert state == snapshot


def test_applier_rejects_incoherent_source_state() -> None:
    entry = desired_entry()
    state = runtime_state(applied_entry=entry)

    with pytest.raises(EntryReconciliationInvariantError, match="APPLY requires no current"):
        apply_success_confirmation(
            state,
            Apply(entry),
            command(trade_cycle_id="cycle-new", entry=entry),
            applied_confirmation(trade_cycle_id="cycle-new", entry=entry),
        )

    empty_state = runtime_state()
    with pytest.raises(EntryReconciliationInvariantError, match="REPLACE requires"):
        apply_success_confirmation(
            empty_state,
            Replace("cycle-1", entry),
            command(trade_cycle_id="cycle-1", entry=entry),
            applied_confirmation(trade_cycle_id="cycle-1", entry=entry),
        )


def test_replace_rejects_sent_desired_entry_mismatch() -> None:
    original = desired_entry()
    updated = desired_entry(planned_entry_price="101")
    state = runtime_state(applied_entry=original)
    snapshot = replace(state)

    with pytest.raises(EntryReconciliationInvariantError, match="desired entry"):
        apply_success_confirmation(
            state,
            Replace("cycle-1", updated),
            command(trade_cycle_id="cycle-1", entry=original),
            applied_confirmation(trade_cycle_id="cycle-1", entry=updated),
        )

    assert state == snapshot


def test_applier_rejects_no_op_instead_of_returning_a_failure_result() -> None:
    state = runtime_state()

    with pytest.raises(
        EntryReconciliationInvariantError,
        match="requires APPLY, REPLACE, or CANCEL",
    ):
        apply_success_confirmation(
            state,
            cast("Apply | Replace | Cancel", NoOp()),
            command(trade_cycle_id="cycle-new", entry=desired_entry()),
            applied_confirmation(trade_cycle_id="cycle-new", entry=desired_entry()),
        )
