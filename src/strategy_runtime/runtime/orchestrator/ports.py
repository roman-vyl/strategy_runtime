"""Ports consumed by the Strategy Runtime orchestrator."""

from collections.abc import Mapping
from typing import Protocol

from strategy_runtime.utility.processing_journal.models import JsonValue


class LiveEntryEvaluationJournalPort(Protocol):
    """Record the Engine live-entry answer for one strategy instance and bar.

    Implementations are best effort and must not raise into orchestration.
    """

    def live_entry_evaluated(
        self,
        *,
        strategy_instance_id: str,
        instrument: str,
        timeframe: str,
        bar_open_time_ms: int,
        desired_entry: Mapping[str, JsonValue] | None,
    ) -> None: ...


class OpenTradeEvaluationJournalPort(Protocol):
    """Record the Engine open-trade answer for one open trade cycle and bar.

    `desired_protection` and `close_signal` are Engine's answer as received,
    prices in Engine's own text. Implementations are best effort and must not
    raise into orchestration.
    """

    def open_trade_evaluated(
        self,
        *,
        strategy_instance_id: str,
        instrument: str,
        timeframe: str,
        bar_open_time_ms: int,
        trade_cycle_id: str,
        side: str,
        desired_protection: Mapping[str, JsonValue],
        close_signal: Mapping[str, JsonValue],
    ) -> None: ...
