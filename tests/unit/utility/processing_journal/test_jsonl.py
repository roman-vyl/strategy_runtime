import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

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


def test_live_entry_evaluated_serializes_desired_entry_and_null(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)
    desired_entry = {
        "side": "long",
        "source_plan_bar_open_time_ms": 900,
        "planned_entry_price": "100.5",
        "initial_stop_price": "99",
        "initial_take_price": "103.25",
        "locked_exit_profile": "runner",
    }

    journal.live_entry_evaluated(
        strategy_instance_id="dep-a",
        instrument="BTCUSDT.P",
        timeframe="5m",
        bar_open_time_ms=1000,
        desired_entry=desired_entry,
    )
    journal.live_entry_evaluated(
        strategy_instance_id="dep-a",
        instrument="BTCUSDT.P",
        timeframe="5m",
        bar_open_time_ms=1300,
        desired_entry=None,
    )

    with_entry, without_entry = (json.loads(line) for line in path.read_text().splitlines())
    assert with_entry["event_type"] == "live_entry_evaluated"
    assert with_entry["schema_version"] == 2
    assert with_entry["strategy_instance_id"] == "dep-a"
    assert with_entry["payload"] == {
        "instrument": "BTCUSDT.P",
        "timeframe": "5m",
        "bar_open_time_ms": 1000,
        "desired_entry": desired_entry,
    }
    assert without_entry["payload"]["bar_open_time_ms"] == 1300
    assert without_entry["payload"]["desired_entry"] is None
    assert "desired_entry" in without_entry["payload"]


def test_appends_are_fsynced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    journal = make_journal(tmp_path / "runtime.jsonl")

    journal.orchestration_started(event=CommittedBarEvent("BTCUSDT.P", "5m", 123))

    assert len(synced) == 1


def test_fsync_failure_is_absorbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_fsync(fd: int) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    journal = make_journal(tmp_path / "runtime.jsonl")

    journal.live_entry_evaluated(
        strategy_instance_id="dep-a",
        instrument="BTCUSDT.P",
        timeframe="5m",
        bar_open_time_ms=1000,
        desired_entry=None,
    )

    assert journal.failure_count == 1


def test_entry_package_applied_serializes_its_payload(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)

    journal.entry_package_applied(
        strategy_instance_id="dep-a",
        trade_cycle_id="cycle-1",
        bar_open_time_ms=1000,
        trigger_price="100.5",
        stop_loss="99",
        take_profit=None,
        quantity="0.002",
        order_link_id="link-1",
        order_id=None,
    )

    record = json.loads(path.read_text())
    assert record["event_type"] == "entry_package_applied"
    assert record["schema_version"] == 2
    assert record["severity"] == "info"
    assert record["strategy_instance_id"] == "dep-a"
    assert record["payload"] == {
        "trade_cycle_id": "cycle-1",
        "bar_open_time_ms": 1000,
        "trigger_price": "100.5",
        "stop_loss": "99",
        "take_profit": None,
        "quantity": "0.002",
        "order_link_id": "link-1",
        "order_id": None,
    }


def test_trade_cycle_opened_serializes_its_payload(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)

    journal.trade_cycle_opened(
        strategy_instance_id="dep-a",
        trade_cycle_id="cycle-1",
        bar_open_time_ms=None,
        first_fill_at_ms=1_000_950,
        average_entry_price="100.5",
        entry_order_link_id="abi-ep-link",
        entry_order_id=None,
    )

    record = json.loads(path.read_text())
    assert record["event_type"] == "trade_cycle_opened"
    assert record["schema_version"] == 2
    assert record["severity"] == "info"
    assert record["strategy_instance_id"] == "dep-a"
    assert record["payload"] == {
        "trade_cycle_id": "cycle-1",
        "bar_open_time_ms": None,
        "first_fill_at_ms": 1_000_950,
        "average_entry_price": "100.5",
        "entry_order_link_id": "abi-ep-link",
        "entry_order_id": None,
    }


def test_trade_cycle_opened_failure_is_absorbed(tmp_path: Path) -> None:
    path = tmp_path / "blocked"
    path.mkdir()
    journal = make_journal(path)

    journal.trade_cycle_opened(
        strategy_instance_id="dep-a",
        trade_cycle_id="cycle-1",
        bar_open_time_ms=1000,
        first_fill_at_ms=950,
        average_entry_price="100.5",
        entry_order_link_id="abi-ep-link",
        entry_order_id="bybit-order-1",
    )

    assert journal.failure_count == 1


def test_open_trade_evaluated_serializes_its_payload(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)

    journal.open_trade_evaluated(
        strategy_instance_id="dep-a",
        instrument="BTCUSDT.P",
        timeframe="5m",
        bar_open_time_ms=1000,
        trade_cycle_id="cycle-1",
        side="short",
        desired_protection={"stop_price": "105.150", "take_price": None},
        close_signal={"active": False, "reason": None, "component_id": None, "layer": None},
    )

    record = json.loads(path.read_text())
    assert record["event_type"] == "open_trade_evaluated"
    assert record["schema_version"] == 2
    assert record["severity"] == "info"
    assert record["strategy_instance_id"] == "dep-a"
    assert record["diagnostics"] == {}
    assert record["payload"] == {
        "instrument": "BTCUSDT.P",
        "timeframe": "5m",
        "bar_open_time_ms": 1000,
        "trade_cycle_id": "cycle-1",
        "side": "short",
        "desired_protection": {"stop_price": "105.150", "take_price": None},
        "close_signal": {"active": False, "reason": None, "component_id": None, "layer": None},
    }


def test_protection_applied_serializes_its_payload(tmp_path: Path) -> None:
    path = tmp_path / "runtime.jsonl"
    journal = make_journal(path)

    journal.protection_applied(
        strategy_instance_id="dep-a",
        trade_cycle_id="cycle-1",
        bar_open_time_ms=1000,
        requested_protection={"stop_price": "99", "take_price": None},
        confirmed_protection={"stop_price": "99", "take_price": None},
        position_quantity="0.010",
        stop_order={"order_id": "stop-1", "trigger_price": "99.0"},
        take_order={"order_id": "take-1", "trigger_price": "990000"},
    )

    record = json.loads(path.read_text())
    assert record["event_type"] == "protection_applied"
    assert record["schema_version"] == 2
    assert record["severity"] == "info"
    assert record["strategy_instance_id"] == "dep-a"
    assert record["diagnostics"] == {}
    assert record["payload"] == {
        "trade_cycle_id": "cycle-1",
        "bar_open_time_ms": 1000,
        "requested_protection": {"stop_price": "99", "take_price": None},
        "confirmed_protection": {"stop_price": "99", "take_price": None},
        "position_quantity": "0.010",
        "stop_order": {"order_id": "stop-1", "trigger_price": "99.0"},
        "take_order": {"order_id": "take-1", "trigger_price": "990000"},
    }


def test_open_trade_events_failures_are_absorbed(tmp_path: Path) -> None:
    path = tmp_path / "blocked"
    path.mkdir()
    journal = make_journal(path)

    journal.open_trade_evaluated(
        strategy_instance_id="dep-a",
        instrument="BTCUSDT.P",
        timeframe="5m",
        bar_open_time_ms=1000,
        trade_cycle_id="cycle-1",
        side="long",
        desired_protection={"stop_price": "99", "take_price": "103"},
        close_signal={"active": False, "reason": None, "component_id": None, "layer": None},
    )
    journal.protection_applied(
        strategy_instance_id="dep-a",
        trade_cycle_id="cycle-1",
        bar_open_time_ms=1000,
        requested_protection={"stop_price": "99", "take_price": "103"},
        confirmed_protection={"stop_price": "99", "take_price": "103"},
        position_quantity="0.01",
        stop_order={"order_id": "stop-1", "trigger_price": "99"},
        take_order={"order_id": "take-1", "trigger_price": "103"},
    )

    assert journal.failure_count == 2
