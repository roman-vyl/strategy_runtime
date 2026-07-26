"""Runtime-owned trade-cycle identity boundary."""

from collections.abc import Callable

from strategy_runtime.shared.identifiers import new_identifier

TradeCycleIdFactory = Callable[[], str]


def new_trade_cycle_id() -> str:
    """Return a production-unique opaque identity for one new trade cycle."""
    return new_identifier()
