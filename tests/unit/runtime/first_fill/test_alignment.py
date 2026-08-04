from typing import cast

import pytest

from strategy_runtime.runtime.first_fill.alignment import align_first_fill_to_entry_bar


def test_fill_inside_candle_rounds_down_to_candle_open() -> None:
    assert align_first_fill_to_entry_bar(905_000, "15m") == 900_000


def test_fill_exactly_on_boundary_stays_on_boundary() -> None:
    assert align_first_fill_to_entry_bar(900_000, "15m") == 900_000


@pytest.mark.parametrize(
    ("base_timeframe", "duration_ms"),
    [
        ("1m", 60_000),
        ("5m", 5 * 60_000),
        ("15m", 15 * 60_000),
        ("1h", 60 * 60_000),
        ("4h", 4 * 60 * 60_000),
        ("1d", 24 * 60 * 60_000),
    ],
)
@pytest.mark.parametrize("offset_ms", [0, 1, 1_234, 59_999])
def test_alignment_is_exact_multiple_and_never_after_the_fill(
    base_timeframe: str,
    duration_ms: int,
    offset_ms: int,
) -> None:
    first_fill_at_ms = duration_ms * 7 + offset_ms
    aligned = align_first_fill_to_entry_bar(first_fill_at_ms, base_timeframe)

    assert aligned % duration_ms == 0
    assert aligned <= first_fill_at_ms


@pytest.mark.parametrize("value", [0, -1, "1000", True, 1.0, None])
def test_rejects_non_positive_or_non_integer_first_fill(value: object) -> None:
    with pytest.raises(ValueError, match="first_fill_at_ms"):
        align_first_fill_to_entry_bar(cast("int", value), "15m")


@pytest.mark.parametrize("base_timeframe", ["", "7m", "1M", "15M", "1H", "unknown"])
def test_rejects_unsupported_base_timeframe(base_timeframe: str) -> None:
    with pytest.raises(ValueError, match="unsupported base_timeframe"):
        align_first_fill_to_entry_bar(1_000, base_timeframe)
