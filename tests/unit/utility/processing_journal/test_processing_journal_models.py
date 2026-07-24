import pytest

from strategy_runtime.utility.processing_journal import (
    ProcessingJournalEvent,
    ProcessingJournalEventType,
)


def test_event_freezes_nested_json() -> None:
    payload = {"nested": {"values": [1, 2]}}
    event = ProcessingJournalEvent(
        schema_version=1,
        event_id="event-1",
        event_type=ProcessingJournalEventType.COMMITTED_BAR_ORCHESTRATION_STARTED,
        occurred_at="2026-07-21T00:00:00Z",
        source="runtime",
        severity="info",
        payload=payload,
        diagnostics={},
    )
    payload["nested"]["values"].append(3)
    assert event.to_dict()["payload"] == {"nested": {"values": [1, 2]}}


def test_event_rejects_non_json_safe_payload() -> None:
    with pytest.raises(TypeError):
        ProcessingJournalEvent(
            schema_version=1,
            event_id="event-1",
            event_type=ProcessingJournalEventType.COMMITTED_BAR_ORCHESTRATION_STARTED,
            occurred_at="2026-07-21T00:00:00Z",
            source="runtime",
            severity="info",
            payload={"bad": object()},
            diagnostics={},
        )
