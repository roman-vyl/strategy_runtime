"""Pure lifetime boundary of a touch_trigger entry order, counted from its signal bar."""


def entry_order_expiration_ms(
    source_plan_bar_open_time_ms: int, timeframe_ms: int, order_lifetime_bars: int
) -> int:
    """Return the close time of the last bar the entry order may live through."""
    if type(source_plan_bar_open_time_ms) is not int or source_plan_bar_open_time_ms < 0:
        raise ValueError("source_plan_bar_open_time_ms must be a non-negative integer")
    if type(timeframe_ms) is not int or timeframe_ms <= 0:
        raise ValueError("timeframe_ms must be a positive integer")
    if type(order_lifetime_bars) is not int or order_lifetime_bars < 0:
        raise ValueError("order_lifetime_bars must be an integer >= 0")
    return source_plan_bar_open_time_ms + (order_lifetime_bars + 2) * timeframe_ms


def is_entry_order_expired(
    current_bar_open_time_ms: int, timeframe_ms: int, expiration_ms: int
) -> bool:
    """The entry order ends on the bar that closes at or after its expiration."""
    return current_bar_open_time_ms + timeframe_ms >= expiration_ms
