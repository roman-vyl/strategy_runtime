import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    CommittedBarOrchestrationResult,
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal


def make_journal(path: Path) -> JsonlProcessingJournal:
    counter = iter(range(1, 100))
    return JsonlProcessingJournal(
        path,
        event_id_factory=lambda: f"event-{next(counter)}",
        timestamp_factory=lambda: "2026-07-21T00:00:00Z",
    )


def test_serializes_semantic_events_and_appends(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "runtime.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"existing":true}\n', encoding="utf-8")
    journal = make_journal(path)
    event = CommittedBarEvent("BTCUSDT.P", "5m", 123)
    success = StrategyCycleDispatchOutcome.succeeded("dep-a")
    failure = StrategyCycleDispatchOutcome.failed("dep-b", error_code="boom")
    result = CommittedBarOrchestrationResult(
        selected_count=2,
        attempted_count=2,
        succeeded_count=1,
        failed_count=1,
        outcomes=(success, failure),
    )

    journal.orchestration_started(event=event)
    journal.strategy_cycle_outcome(event=event, outcome=success)
    journal.strategy_cycle_outcome(event=event, outcome=failure)
    journal.orchestration_completed(event=event, result=result)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0] == {"existing": True}
    assert [record["event_type"] for record in records[1:]] == [
        "committed_bar_orchestration_started",
        "strategy_cycle_dispatch_succeeded",
        "strategy_cycle_dispatch_failed",
        "committed_bar_orchestration_completed",
    ]
    assert set(records[1]) == {
        "schema_version",
        "event_id",
        "event_type",
        "occurred_at",
        "source",
        "severity",
        "payload",
        "diagnostics",
    }
    assert records[1]["payload"] == {
        "instrument": "BTCUSDT.P",
        "open_time_ms": 123,
        "timeframe": "5m",
    }
    assert records[3]["strategy_instance_id"] == "dep-b"
    assert records[4]["severity"] == "warning"
    assert records[4]["payload"]["selected_count"] == 2
    assert "raw_spec" not in path.read_text()


def test_orchestration_failure_is_serialized(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)
    journal.orchestration_failed(
        event=CommittedBarEvent("BTCUSDT.P", "5m", 123),
        stage="deployment_catalog",
        error=RuntimeError("boom"),
    )
    record = json.loads(path.read_text())
    assert record["event_type"] == "committed_bar_orchestration_failed"
    assert record["payload"]["stage"] == "deployment_catalog"
    assert record["diagnostics"]["error_type"] == "RuntimeError"


def test_failures_are_absorbed(tmp_path: Path) -> None:
    path = tmp_path / "blocked"
    path.mkdir()
    journal = make_journal(path)
    journal.orchestration_started(
        event=CommittedBarEvent("BTCUSDT.P", "5m", 123),
    )
    assert journal.failure_count == 1


def test_concurrent_writes_produce_complete_lines(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)
    event = CommittedBarEvent("BTCUSDT.P", "5m", 123)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: journal.strategy_cycle_outcome(
                    event=event,
                    outcome=StrategyCycleDispatchOutcome.succeeded(f"dep-{index}"),
                ),
                range(20),
            )
        )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 20


def test_serialization_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)
    journal.orchestration_started(
        event=CommittedBarEvent("BTCUSDT.P", "5m", 123),
    )
    line = path.read_text().strip()
    assert line == json.dumps(
        json.loads(line), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
