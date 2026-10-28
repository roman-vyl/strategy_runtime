"""Journal port for entry attempts that ended without a fill."""

from typing import Protocol


class EntryCycleEndedJournalPort(Protocol):
    """Record that one entry attempt ended without a fill, after the durable save.

    `bar_open_time_ms` is the committed bar on which Runtime ended it, or `None`
    when it ended outside bar processing (a disable or the uncertain-state resolver).
    Implementations are best effort and must not raise into orchestration.
    """

    def entry_cycle_ended(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int | None,
        reason: str,
    ) -> None: ...
