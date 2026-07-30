import json
from pathlib import Path

from strategy_runtime.shared.identifiers import new_identifier, utc_timestamp
from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentSpecification,
    FilesystemDeploymentCatalog,
)
from strategy_runtime.utility.deployment_selection import CommittedBarDeploymentSelector
from strategy_runtime.utility.handoff import StrategyCycleHandoffBoundary
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal


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


def test_utility_contour_selects_and_dispatches_matching_deployment(tmp_path: Path) -> None:
    """Exercise the utility contour in isolation, without `build_application`.

    `build_application` no longer has a utility-only ready result (it always
    requires and constructs the complete semantic/outbound production graph),
    so the utility contour's own isolated testability is proven by
    constructing its components directly, exactly as production composition
    does internally.
    """
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
    journal_path.parent.mkdir(parents=True)
    received: list[StrategyBarProcessingUnit[DeploymentSpecification]] = []

    catalog = FilesystemDeploymentCatalog(specs_path)
    selector = CommittedBarDeploymentSelector()
    journal = JsonlProcessingJournal(
        journal_path,
        event_id_factory=new_identifier,
        timestamp_factory=utc_timestamp,
    )
    handoff_boundary = StrategyCycleHandoffBoundary(received.append)
    orchestrator = CommittedBarOrchestrator(
        deployment_catalog=catalog,
        deployment_selector=selector,
        strategy_cycle_dispatcher=handoff_boundary,
        processing_journal=journal,
    )

    orchestrator.process(
        CommittedBarEvent(instrument="BTCUSDT.P", timeframe="5m", open_time_ms=12345)
    )

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
