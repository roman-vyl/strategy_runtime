"""Pure fill-timestamp-to-entry-bar alignment."""

from strategy_runtime.runtime.timeframe import timeframe_duration_ms


def align_first_fill_to_entry_bar(first_fill_at_ms: int, base_timeframe: str) -> int:
    """Floor a fill timestamp to its containing candle's open time."""
    if type(first_fill_at_ms) is not int or first_fill_at_ms <= 0:
        raise ValueError("first_fill_at_ms must be a strictly positive integer")
    duration_ms = timeframe_duration_ms(base_timeframe)
    return first_fill_at_ms - (first_fill_at_ms % duration_ms)
