"""Reasons an entry attempt ends without a fill, and the one journaling helper."""

from typing import Final

from strategy_runtime.runtime.entry_cycle_ended.ports import EntryCycleEndedJournalPort

CANCELLED: Final = "cancelled"
DISABLED: Final = "disabled"
TERMINAL_WITHOUT_FILL: Final = "terminal_without_fill"
EXACT_ABSENT: Final = "exact_absent"
ENTRY_CYCLE_END_REASONS: Final = frozenset(
    {CANCELLED, DISABLED, TERMINAL_WITHOUT_FILL, EXACT_ABSENT}
)


def journal_entry_cycle_ended(
    journal: EntryCycleEndedJournalPort | None,
    *,
    strategy_instance_id: str,
    trade_cycle_id: str,
    bar_open_time_ms: int | None,
    reason: str,
) -> None:
    """Write one `entry_cycle_ended` record; call only after the durable save."""
    if journal is None:
        return
    if reason not in ENTRY_CYCLE_END_REASONS:
        raise ValueError(f"unsupported entry cycle end reason: {reason!r}")
    journal.entry_cycle_ended(
        strategy_instance_id=strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        bar_open_time_ms=bar_open_time_ms,
        reason=reason,
    )
