import json
import logging
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.committed_bar_intake import (
    CommittedBarIntakeBoundary,
    CommittedBarIntakeWorker,
)
from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    SelectedDeployment,
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentSpecification,
    FilesystemDeploymentCatalog,
)


class ExactStreamSelector:
    def select(
        self,
        *,
        event: CommittedBarEvent,
        snapshot: DeploymentCatalogSnapshot,
    ) -> tuple[SelectedDeployment[DeploymentSpecification], ...]:
        return tuple(
            SelectedDeployment(item.strategy_instance_id, item)
            for item in snapshot.accepted_deployments
            if item.enabled
            and item.instrument == event.instrument
            and item.base_timeframe == event.timeframe
        )


class RecordingDispatcher:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def dispatch(self, unit):
        self.ids.append(unit.strategy_instance_id)
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[str] = []

    def orchestration_started(self, **_kwargs) -> None:
        self.events.append("started")

    def orchestration_failed(self, **_kwargs) -> None:
        self.events.append("failed")

    def strategy_cycle_outcome(self, **_kwargs) -> None:
        self.events.append("cycle")

    def orchestration_completed(self, **_kwargs) -> None:
        self.events.append("completed")


def _write_deployment(path: Path, *, ticker: str, timeframe: str, fast_ema: int) -> None:
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "ticker": ticker,
                "base_timeframe": timeframe,
                "strategy_id": "ema_pullback",
                "raw_spec": {
                    "family": "ema_pullback",
                    "direction": {"fast_ema": fast_ema, "anchor_ema": 200},
                    "setups": [{"type": "untouched_anchor_setup"}],
                    "triggers": [{"type": "reclaim_anchor"}],
                    "exit_policy": {"mode": "managed"},
                },
            }
        ),
        encoding="utf-8",
    )


def test_fake_webhook_runs_catalog_and_orchestrator_against_bbb_like_specs(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    _write_deployment(specs / "btc-a.json", ticker="BTCUSDT.P", timeframe="5m", fast_ema=20)
    _write_deployment(specs / "btc-b.json", ticker="BTCUSDT.P", timeframe="5m", fast_ema=21)
    _write_deployment(specs / "eth.json", ticker="ETHUSDT.P", timeframe="5m", fast_ema=20)
    (specs / "broken.json").write_text("{broken", encoding="utf-8")

    dispatcher = RecordingDispatcher()
    journal = RecordingJournal()
    orchestrator = CommittedBarOrchestrator(
        deployment_catalog=FilesystemDeploymentCatalog(specs),
        deployment_selector=ExactStreamSelector(),
        strategy_cycle_dispatcher=dispatcher,
        processing_journal=journal,
    )
    results = []
    processed = threading.Event()
    real_process = orchestrator.process

    def _recording_process(event: CommittedBarEvent) -> object:
        try:
            result = real_process(event)
            results.append(result)
            return result
        finally:
            processed.set()

    orchestrator.process = _recording_process  # type: ignore[method-assign]

    intake = CommittedBarIntakeBoundary(capacity=8)
    worker = CommittedBarIntakeWorker(intake, orchestrator, logging.getLogger("test"))
    worker.start()
    try:
        app = create_http_app(
            ready=True,
            committed_bar_intake=intake,
            process_first_fill=None,
        )
        response = TestClient(app).post(
            "/v1/webhooks/closed-bar",
            json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 12345},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "accepted"}
        assert processed.wait(timeout=5), "intake worker never processed the accepted event"
    finally:
        intake.stop_accepting()
        worker.stop_once()

    preflight_snapshot = FilesystemDeploymentCatalog(specs).load_snapshot()
    expected_ids = [
        item.strategy_instance_id
        for item in preflight_snapshot.accepted_deployments
        if item.instrument == "BTCUSDT.P"
    ]
    assert sorted(dispatcher.ids) == sorted(expected_ids)
    assert len(results) == 1
    assert results[0].selected_count == 2
    assert results[0].succeeded_count == 2
    assert journal.events == ["started", "cycle", "cycle", "completed"]

    snapshot = FilesystemDeploymentCatalog(specs).load_snapshot()
    assert snapshot.scanned_file_count == 4
    assert [item.source_path for item in snapshot.invalid_files] == ["broken.json"]
