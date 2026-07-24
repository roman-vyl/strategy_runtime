import json
from pathlib import Path

from fastapi.testclient import TestClient

from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.utility.committed_bar import StrategyBarProcessingUnit
from strategy_runtime.utility.deployment_catalog import DeploymentSpecification


def _write_deployment(
    path: Path,
    *,
    enabled: bool,
    ticker: str,
    timeframe: str = "5m",
    fast_ema: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "enabled": enabled,
                "ticker": ticker,
                "base_timeframe": timeframe,
                "strategy_id": "ema_pullback",
                "raw_spec": {
                    "direction": {"fast_ema": fast_ema, "anchor_ema": 200},
                    "setups": [{"type": "untouched_anchor_setup"}],
                    "triggers": [{"type": "reclaim_anchor"}],
                },
            }
        ),
        encoding="utf-8",
    )


def test_production_composition_runs_the_complete_utility_contour(tmp_path: Path) -> None:
    specs_path = tmp_path / "specs"
    specs_path.mkdir()
    _write_deployment(
        specs_path / "selected.json",
        enabled=True,
        ticker="BTCUSDT.P",
        fast_ema=20,
    )
    _write_deployment(
        specs_path / "disabled.json",
        enabled=False,
        ticker="BTCUSDT.P",
        fast_ema=21,
    )
    _write_deployment(
        specs_path / "other-market.json",
        enabled=True,
        ticker="ETHUSDT.P",
        fast_ema=22,
    )
    journal_path = tmp_path / "journal" / "runtime.jsonl"
    received: list[StrategyBarProcessingUnit[DeploymentSpecification]] = []

    app = build_application(
        {
            "RUNTIME_SPECS_PATH": str(specs_path),
            "RUNTIME_JOURNAL_PATH": str(journal_path),
        },
        strategy_cycle_handoff=received.append,
    )

    response = TestClient(app).post(
        "/v1/webhooks/closed-bar",
        json={
            "instrument": "BTCUSDT.P",
            "timeframe": "5m",
            "open_time_ms": 12345,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert len(received) == 1
    assert received[0].deployment.source_path == "selected.json"
    assert received[0].strategy_instance_id == received[0].deployment.strategy_instance_id
    assert received[0].committed_bar.open_time_ms == 12345

    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event_type"] for record in records] == [
        "committed_bar_orchestration_started",
        "strategy_cycle_dispatch_succeeded",
        "committed_bar_orchestration_completed",
    ]
    assert records[1]["strategy_instance_id"] == received[0].strategy_instance_id
    assert all("trace_id" not in record for record in records)
