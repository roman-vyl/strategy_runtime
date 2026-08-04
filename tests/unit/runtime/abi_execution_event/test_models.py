import dataclasses

import pytest

from strategy_runtime.runtime.abi_execution_event.models import AbiFirstFillExecutionEvent

VALID_STRATEGY_INSTANCE_ID = "instance-a"
VALID_TRADE_CYCLE_ID = "cycle-1"
VALID_FIRST_FILL_AT_MS = 905_000


def _make(
    *,
    strategy_instance_id: object = VALID_STRATEGY_INSTANCE_ID,
    trade_cycle_id: object = VALID_TRADE_CYCLE_ID,
    first_fill_at_ms: object = VALID_FIRST_FILL_AT_MS,
) -> AbiFirstFillExecutionEvent:
    return AbiFirstFillExecutionEvent(
        strategy_instance_id=strategy_instance_id,  # type: ignore[arg-type]
        trade_cycle_id=trade_cycle_id,  # type: ignore[arg-type]
        first_fill_at_ms=first_fill_at_ms,  # type: ignore[arg-type]
    )


def test_valid_event_carries_fields_unchanged() -> None:
    event = _make()

    assert event.strategy_instance_id == VALID_STRATEGY_INSTANCE_ID
    assert event.trade_cycle_id == VALID_TRADE_CYCLE_ID
    assert event.first_fill_at_ms == VALID_FIRST_FILL_AT_MS


def test_no_entry_bar_open_time_ms_field_exists() -> None:
    field_names = {f.name for f in dataclasses.fields(AbiFirstFillExecutionEvent)}

    assert field_names == {"strategy_instance_id", "trade_cycle_id", "first_fill_at_ms"}
    assert "entry_bar_open_time_ms" not in field_names


@pytest.mark.parametrize("bad_strategy_instance_id", ["", 123, None, b"instance"])
def test_reject_non_string_or_empty_strategy_instance_id(bad_strategy_instance_id: object) -> None:
    with pytest.raises(ValueError, match="strategy_instance_id"):
        _make(strategy_instance_id=bad_strategy_instance_id)


@pytest.mark.parametrize("bad_trade_cycle_id", ["", 123, None, b"cycle"])
def test_reject_non_string_or_empty_trade_cycle_id(bad_trade_cycle_id: object) -> None:
    with pytest.raises(ValueError, match="trade_cycle_id"):
        _make(trade_cycle_id=bad_trade_cycle_id)


@pytest.mark.parametrize("bad_timestamp", [0, -1, "905000", None])
def test_reject_non_positive_or_non_integer_first_fill_at_ms(bad_timestamp: object) -> None:
    with pytest.raises(ValueError, match="first_fill_at_ms"):
        _make(first_fill_at_ms=bad_timestamp)


@pytest.mark.parametrize("boolean_timestamp", [True, False])
def test_reject_boolean_first_fill_at_ms(boolean_timestamp: bool) -> None:
    with pytest.raises(ValueError, match="first_fill_at_ms"):
        _make(first_fill_at_ms=boolean_timestamp)


def test_reject_float_first_fill_at_ms() -> None:
    with pytest.raises(ValueError, match="first_fill_at_ms"):
        _make(first_fill_at_ms=1_700_000_000_000.0)


@pytest.mark.parametrize(
    "field",
    ["strategy_instance_id", "trade_cycle_id", "first_fill_at_ms"],
)
def test_invalid_event_never_becomes_a_usable_instance(field: str) -> None:
    """An invalid event raises during construction, so no caller can ever hold
    a half-valid AbiFirstFillExecutionEvent to pass into
    AbiExecutionEventOrchestrator.process(...) — there is nothing downstream
    (mutex, repository) to reach."""
    kwargs: dict[str, object] = {
        "strategy_instance_id": VALID_STRATEGY_INSTANCE_ID,
        "trade_cycle_id": VALID_TRADE_CYCLE_ID,
        "first_fill_at_ms": VALID_FIRST_FILL_AT_MS,
    }
    kwargs[field] = "" if field != "first_fill_at_ms" else 0

    with pytest.raises(ValueError):
        AbiFirstFillExecutionEvent(**kwargs)  # type: ignore[arg-type]
