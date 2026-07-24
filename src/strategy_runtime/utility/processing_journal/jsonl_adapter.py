"""Best-effort append-only JSONL processing journal."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Final

from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    CommittedBarOrchestrationResult,
    StrategyCycleDispatchOutcome,
    StrategyCycleDispatchStatus,
)
from strategy_runtime.utility.processing_journal.models import (
    JsonValue,
    ProcessingJournalEvent,
    ProcessingJournalEventType,
)

IdentifierFactory = Callable[[], str]
TimestampFactory = Callable[[], str]

_SCHEMA_VERSION: Final = 1
_SOURCE: Final = "strategy_runtime.committed_bar_orchestrator"


class JsonlProcessingJournal:
    """Implement the orchestrator's semantic journal port without raising failures."""

    def __init__(
        self,
        path: Path,
        *,
        event_id_factory: IdentifierFactory,
        timestamp_factory: TimestampFactory,
        logger: logging.Logger | None = None,
    ) -> None:
        self._path = path
        self._event_id_factory = event_id_factory
        self._timestamp_factory = timestamp_factory
        self._logger = logger or logging.getLogger(__name__)
        self._lock = Lock()
        self._failure_count = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def orchestration_started(
        self,
        *,
        event: CommittedBarEvent,
    ) -> None:
        self._record(
            event_type=ProcessingJournalEventType.COMMITTED_BAR_ORCHESTRATION_STARTED,
            severity="info",
            payload=_bar_payload(event),
        )

    def orchestration_failed(
        self,
        *,
        event: CommittedBarEvent,
        stage: str,
        error: Exception,
    ) -> None:
        self._record(
            event_type=ProcessingJournalEventType.COMMITTED_BAR_ORCHESTRATION_FAILED,
            severity="error",
            payload={**_bar_payload(event), "stage": stage},
            diagnostics={
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )

    def strategy_cycle_outcome(
        self,
        *,
        event: CommittedBarEvent,
        outcome: StrategyCycleDispatchOutcome,
    ) -> None:
        succeeded = outcome.status is StrategyCycleDispatchStatus.SUCCEEDED
        self._record(
            event_type=(
                ProcessingJournalEventType.STRATEGY_CYCLE_DISPATCH_SUCCEEDED
                if succeeded
                else ProcessingJournalEventType.STRATEGY_CYCLE_DISPATCH_FAILED
            ),
            strategy_instance_id=outcome.strategy_instance_id,
            severity="info" if succeeded else "error",
            payload={**_bar_payload(event), "status": outcome.status.value},
            diagnostics=(
                {}
                if succeeded
                else {
                    "error_code": outcome.error_code,
                    "error_message": outcome.error_message,
                }
            ),
        )

    def orchestration_completed(
        self,
        *,
        event: CommittedBarEvent,
        result: CommittedBarOrchestrationResult,
    ) -> None:
        self._record(
            event_type=ProcessingJournalEventType.COMMITTED_BAR_ORCHESTRATION_COMPLETED,
            severity="info" if result.failed_count == 0 else "warning",
            payload={
                **_bar_payload(event),
                "selected_count": result.selected_count,
                "attempted_count": result.attempted_count,
                "succeeded_count": result.succeeded_count,
                "failed_count": result.failed_count,
            },
        )

    def _record(
        self,
        *,
        event_type: ProcessingJournalEventType,
        severity: str,
        payload: dict[str, JsonValue],
        diagnostics: dict[str, JsonValue] | None = None,
        strategy_instance_id: str | None = None,
    ) -> None:
        try:
            event = ProcessingJournalEvent(
                schema_version=_SCHEMA_VERSION,
                event_id=self._event_id_factory(),
                event_type=event_type,
                occurred_at=self._timestamp_factory(),
                source=_SOURCE,
                strategy_instance_id=strategy_instance_id,
                severity=severity,
                payload=payload,
                diagnostics=diagnostics or {},
            )
            record = json.dumps(
                event.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(record)
                    handle.write("\n")
                    handle.flush()
        except Exception:
            self._failure_count += 1
            self._logger.exception(
                "Processing journal event could not be persisted",
                extra={"event_type": event_type.value},
            )


def _bar_payload(event: CommittedBarEvent) -> dict[str, JsonValue]:
    return {
        "instrument": event.instrument,
        "timeframe": event.timeframe,
        "open_time_ms": event.open_time_ms,
    }
