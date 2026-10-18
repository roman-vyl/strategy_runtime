"""Journal port for ABI-proven trade-cycle closures."""

from typing import Protocol


class TradeCycleClosedJournalPort(Protocol):
    """Record one ABI-proven closure after the state without the cycle was saved.

    `bar_open_time_ms` is the committed bar on which Runtime learned of the
    closure, or `None` when the pending-close resolver learned of it.
    Implementations are best effort and must not raise into orchestration.
    """

    def trade_cycle_closed(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int | None,
        reason: str,
        order_id: str,
        order_link_id: str | None,
        parent_order_link_id: str | None,
    ) -> None: ...
