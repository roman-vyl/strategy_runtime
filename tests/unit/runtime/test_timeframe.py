import pytest

from strategy_runtime.runtime.timeframe import timeframe_duration_ms


@pytest.mark.parametrize(
    ("base_timeframe", "expected"),
    [
        ("1m", 60_000),
        ("5m", 300_000),
        ("15m", 900_000),
        ("1h", 3_600_000),
        ("4h", 14_400_000),
        ("1d", 86_400_000),
    ],
)
def test_supported_timeframes(base_timeframe: str, expected: int) -> None:
    assert timeframe_duration_ms(base_timeframe) == expected


def test_unsupported_timeframe_is_an_error() -> None:
    with pytest.raises(ValueError, match="unsupported base_timeframe: '2m'"):
        timeframe_duration_ms("2m")
