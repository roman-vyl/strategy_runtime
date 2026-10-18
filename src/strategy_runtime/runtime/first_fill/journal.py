"""Journal port for the Open Trade transition (runtime-trade-cycle-opened-v1)."""

from typing import Protocol


class TradeCycleOpenedJournalPort(Protocol):
    """Record one Open Trade transition after the frozen state was saved.

    `bar_open_time_ms` is the committed bar on which Runtime made the
    transition, or `None` when the uncertain-state resolver made it.
    `average_entry_price` is ABI's value at that observation, not a final
    entry price. Implementations are best effort and must not raise into
    orchestration.
    """

    def trade_cycle_opened(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int | None,
        first_fill_at_ms: int,
        average_entry_price: str,
        entry_order_link_id: str,
        entry_order_id: str | None,
    ) -> None: ...


def journal_trade_cycle_opened(
    journal: TradeCycleOpenedJournalPort | None,
    *,
    strategy_instance_id: str,
    trade_cycle_id: str,
    bar_open_time_ms: int | None,
    first_fill_at_ms: int,
    average_entry_price: str,
    entry_order_link_id: str,
    entry_order_id: str | None,
) -> None:
    """Write one `trade_cycle_opened` record; call only after the durable save."""
    if journal is None:
        return
    journal.trade_cycle_opened(
        strategy_instance_id=strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        bar_open_time_ms=bar_open_time_ms,
        first_fill_at_ms=first_fill_at_ms,
        average_entry_price=average_entry_price,
        entry_order_link_id=entry_order_link_id,
        entry_order_id=entry_order_id,
    )
