"""Supported base timeframes and their candle durations."""

_SUPPORTED_TIMEFRAME_DURATIONS_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def timeframe_duration_ms(base_timeframe: str) -> int:
    """Return one candle's duration; an unsupported timeframe is an error."""
    duration_ms = _SUPPORTED_TIMEFRAME_DURATIONS_MS.get(base_timeframe)
    if duration_ms is None:
        raise ValueError(f"unsupported base_timeframe: {base_timeframe!r}")
    return duration_ms
