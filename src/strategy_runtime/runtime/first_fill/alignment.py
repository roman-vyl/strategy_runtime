"""Pure fill-timestamp-to-entry-bar alignment."""

_SUPPORTED_TIMEFRAME_DURATIONS_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def align_first_fill_to_entry_bar(first_fill_at_ms: int, base_timeframe: str) -> int:
    """Floor a fill timestamp to its containing candle's open time."""
    if type(first_fill_at_ms) is not int or first_fill_at_ms <= 0:
        raise ValueError("first_fill_at_ms must be a strictly positive integer")
    duration_ms = _SUPPORTED_TIMEFRAME_DURATIONS_MS.get(base_timeframe)
    if duration_ms is None:
        raise ValueError(f"unsupported base_timeframe: {base_timeframe!r}")
    return first_fill_at_ms - (first_fill_at_ms % duration_ms)
