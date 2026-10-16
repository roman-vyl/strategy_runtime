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
