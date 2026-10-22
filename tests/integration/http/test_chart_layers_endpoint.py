"""HTTP integration tests for GET /v1/strategy-instances/{id}/chart-layers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.chart_layers import errors
from strategy_runtime.runtime.chart_layers.models import ChartLayers, EmaStackEntry, EpisodeEntry
from strategy_runtime.runtime.chart_layers.service import StrategyChartLayersService
from strategy_runtime.runtime.enabled_control import errors as shared
from strategy_runtime.runtime.engine.errors import StrategyEngineProjectionTimeout
from strategy_runtime.utility.deployment_catalog import (
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

RAW_SPEC = {"anchor": 500}
SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec=RAW_SPEC
)
PATH = f"/v1/strategy-instances/{SID}/chart-layers"

LAYERS = ChartLayers(
    strategy_instance_id=SID,
    ema_stack=(
        EmaStackEntry("fast", "base", 200, "close"),
        EmaStackEntry("anchor", "base", 500, "close"),
        EmaStackEntry("slow", "1h", 1000, "close"),
    ),
    episodes=(
        EpisodeEntry("trend", {"fast_period": 200, "anchor_period": 500, "slow_period": 1000}),
    ),
)


class RecordingLogger:
    def info(self, message: str, *args: object, **kwargs: object) -> None: ...

    def exception(self, message: str, *args: object, **kwargs: object) -> None: ...

    def error(self, message: str, **kwargs: object) -> None: ...

    def warning(self, message: str, **kwargs: object) -> None: ...


def client(
    getter: Callable[[str], ChartLayers] | None, *, ready: bool = True, **extra: object
) -> TestClient:
    app = create_http_app(
        ready=ready,
        committed_bar_intake=None,
        process_first_fill=None,
        get_chart_layers=getter,
        logger=RecordingLogger(),  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_success_returns_the_stack_and_the_episodes() -> None:
    calls: list[str] = []

    def getter(sid: str) -> ChartLayers:
        calls.append(sid)
        return LAYERS

    response = client(getter).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "strategy_instance_id": SID,
        "ema_stack": [
            {"role": "fast", "timeframe": "base", "period": 200, "source": "close"},
            {"role": "anchor", "timeframe": "base", "period": 500, "source": "close"},
            {"role": "slow", "timeframe": "1h", "period": 1000, "source": "close"},
        ],
        "episodes": [
            {
                "episode_ref": "trend",
                "params": {"fast_period": 200, "anchor_period": 500, "slow_period": 1000},
            }
        ],
    }
    assert calls == [SID]


def test_no_episodes_is_an_empty_list() -> None:
    body = client(lambda _: ChartLayers(SID, LAYERS.ema_stack, ())).get(PATH).json()
    assert body["episodes"] == []


@pytest.mark.parametrize(
    ("refusal", "status", "reason"),
    [
        (shared.StrategyInstanceNotFound, 404, "strategy_instance_not_found"),
        (shared.CatalogUnavailable, 503, "catalog_unavailable"),
        (errors.EngineUnavailable, 502, "engine_unavailable"),
    ],
)
def test_refusals_are_mapped(refusal: type[Exception], status: int, reason: str) -> None:
    def getter(_: str) -> ChartLayers:
        raise refusal()

    response = client(getter).get(PATH)

    assert response.status_code == status
    assert response.json() == {"status": "chart_layers_refused", "reason": reason}


def test_engine_rejection_carries_engine_code_and_message() -> None:
    def getter(_: str) -> ChartLayers:
        raise errors.EngineRejected(engine_code="unknown_component", engine_message="no such part")

    response = client(getter).get(PATH)

    assert response.status_code == 422
    assert response.json() == {
        "status": "chart_layers_refused",
        "reason": "engine_rejected",
        "engine_code": "unknown_component",
        "engine_message": "no such part",
    }


def test_not_ready_answers_the_not_ready_body_without_calling() -> None:
    calls: list[str] = []

    def getter(sid: str) -> ChartLayers:
        calls.append(sid)
        return LAYERS

    response = client(getter, ready=False).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert calls == []


def test_unexpected_error_is_a_500() -> None:
    def getter(_: str) -> ChartLayers:
        raise RuntimeError("boom")

    assert client(getter).get(PATH).status_code == 500


class _FailingPlan:
    def __init__(self) -> None:
        self.calls = 0

    def build_feature_plan(
        self, strategy_id: str, raw_spec: Mapping[str, object]
    ) -> Mapping[str, object]:
        self.calls += 1
        raise StrategyEngineProjectionTimeout("engine down")


def test_engine_down_leaves_the_list_and_the_files_alone(tmp_path: Path) -> None:
    spec = tmp_path / "a.json"
    spec.write_text(
        json.dumps(
            {
                "enabled": True,
                "ticker": "BTCUSDT.P",
                "base_timeframe": "5m",
                "strategy_id": "ema_pullback",
                "raw_spec": RAW_SPEC,
            }
        )
    )
    before = spec.read_bytes()
    catalog = FilesystemDeploymentCatalog(tmp_path)
    port = _FailingPlan()
    service = StrategyChartLayersService(load_snapshot=catalog.load_snapshot, feature_plan=port)
    http = client(service.get, load_deployment_catalog=catalog.load_snapshot)

    refused = http.get(PATH)
    listed = http.get("/v1/strategy-instances")

    assert refused.status_code == 502
    assert refused.json()["reason"] == "engine_unavailable"
    assert listed.status_code == 200
    assert [item["strategy_instance_id"] for item in listed.json()["strategy_instances"]] == [SID]
    assert port.calls == 1
    assert spec.read_bytes() == before
