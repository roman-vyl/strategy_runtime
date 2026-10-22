"""`StrategyChartLayersService`: stack roles through `anchor_columns`, episodes from the plan."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from strategy_runtime.runtime.chart_layers import errors
from strategy_runtime.runtime.chart_layers.service import StrategyChartLayersService
from strategy_runtime.runtime.engine.errors import (
    StrategyEngineProjectionNetworkFailure,
    StrategyEngineProjectionProtocolError,
    StrategyEngineProjectionPublicError,
    StrategyEngineProjectionTimeout,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogUnavailableError,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue

RAW_SPEC = {"anchor_stack": {"fast": {"period": 200}}}
SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec=RAW_SPEC
)


def ema(output_id: str, period: int, timeframe: str = "base", source: str = "close") -> dict:
    return {
        "output_id": output_id,
        "kind": "ema",
        "timeframe": timeframe,
        "source": source,
        "parameters": {"period": period},
        "dependencies": [],
    }


def plan(**overrides: object) -> dict:
    body: dict = {
        "plan_version": "bbb_v1",
        "plan_hash": "h",
        "features": [
            ema("ema_close_base_200", 200),
            ema("ema_close_base_500", 500),
            ema("ema_close_base_1000", 1000),
        ],
        "anchor_columns": {
            "fast": "ema_close_base_200",
            "anchor": "ema_close_base_500",
            "slow": "ema_close_base_1000",
        },
    }
    body.update(overrides)
    return body


class FakePort:
    def __init__(self, result: Mapping[str, object] | Exception) -> None:
        self._result = result
        self.calls: list[tuple[str, Mapping[str, FrozenJsonValue]]] = []

    def build_feature_plan(
        self, strategy_id: str, raw_spec: Mapping[str, FrozenJsonValue]
    ) -> Mapping[str, object]:
        self.calls.append((strategy_id, raw_spec))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def write_spec(directory: Path, enabled: bool = True) -> None:
    (directory / "a.json").write_text(
        json.dumps(
            {
                "enabled": enabled,
                "ticker": "BTCUSDT.P",
                "base_timeframe": "5m",
                "strategy_id": "ema_pullback",
                "raw_spec": RAW_SPEC,
            }
        )
    )


def service(tmp_path: Path, port: FakePort, *, enabled: bool = True) -> StrategyChartLayersService:
    write_spec(tmp_path, enabled)
    return StrategyChartLayersService(
        load_snapshot=FilesystemDeploymentCatalog(tmp_path).load_snapshot, feature_plan=port
    )


def engine_error(status: int, code: str = "invalid_request") -> StrategyEngineProjectionPublicError:
    return StrategyEngineProjectionPublicError(
        status_code=status, code=code, message="m", details={}, request_id="r"
    )


def test_stack_and_episode_come_from_the_plan(tmp_path: Path) -> None:
    episode = {
        "fast_period": 200,
        "anchor_period": 500,
        "slow_period": 1000,
        "window_bars": 24,
        "break_bars": 24,
        "history_bars": 15000,
    }
    port = FakePort(plan(episode_params_by_ref={"trend": episode}))

    layers = service(tmp_path, port).get(SID)

    assert [(e.role, e.timeframe, e.period, e.source) for e in layers.ema_stack] == [
        ("fast", "base", 200, "close"),
        ("anchor", "base", 500, "close"),
        ("slow", "base", 1000, "close"),
    ]
    assert [(e.episode_ref, dict(e.params)) for e in layers.episodes] == [("trend", episode)]
    assert port.calls == [("ema_pullback", {"anchor_stack": {"fast": {"period": 200}}})]


def test_no_episode_section_gives_no_episodes(tmp_path: Path) -> None:
    assert service(tmp_path, FakePort(plan())).get(SID).episodes == ()


def test_enabled_and_disabled_answer_the_same(tmp_path: Path) -> None:
    on = service(tmp_path, FakePort(plan()), enabled=True).get(SID)
    off = service(tmp_path, FakePort(plan()), enabled=False).get(SID)
    assert on == off


def test_roles_are_resolved_by_mapping_not_by_order(tmp_path: Path) -> None:
    features = [
        ema("ema_close_1h_9", 9, "1h"),
        ema("ema_close_base_1000", 1000),
        ema("ema_close_base_500", 500),
        ema("ema_close_base_200", 200),
    ]

    layers = service(tmp_path, FakePort(plan(features=features))).get(SID)

    assert [(e.role, e.period) for e in layers.ema_stack] == [
        ("fast", 200),
        ("anchor", 500),
        ("slow", 1000),
    ]


def test_base_and_concrete_timeframes_are_copied_unchanged(tmp_path: Path) -> None:
    features = [
        ema("ema_close_1h_200", 200, "1h"),
        ema("ema_close_base_500", 500),
        ema("ema_close_base_1000", 1000, source="hl2"),
    ]
    columns = {
        "fast": "ema_close_1h_200",
        "anchor": "ema_close_base_500",
        "slow": "ema_close_base_1000",
    }

    layers = service(tmp_path, FakePort(plan(features=features, anchor_columns=columns))).get(SID)

    assert [(e.timeframe, e.source) for e in layers.ema_stack] == [
        ("1h", "close"),
        ("base", "close"),
        ("base", "hl2"),
    ]


@pytest.mark.parametrize(
    "broken",
    [
        {"anchor_columns": {"fast": "ema_close_base_200", "anchor": "ema_close_base_500"}},
        {
            "anchor_columns": {
                "fast": "x",
                "anchor": "ema_close_base_500",
                "slow": "ema_close_base_1000",
            }
        },
        {"features": [ema("ema_close_base_200", 200), ema("ema_close_base_500", 500)]},
        {
            "features": [
                ema("ema_close_base_200", 200),
                ema("ema_close_base_500", 500),
                {**ema("ema_close_base_1000", 1000), "kind": "atr"},
            ]
        },
        {
            "features": [
                ema("ema_close_base_200", 0),
                ema("ema_close_base_500", 500),
                ema("ema_close_base_1000", 1000),
            ]
        },
        {
            "features": [
                ema("ema_close_base_200", 200),
                ema("ema_close_base_200", 200),
                ema("ema_close_base_500", 500),
                ema("ema_close_base_1000", 1000),
            ]
        },
        {"episode_params_by_ref": ["trend"]},
    ],
)
def test_an_invalid_plan_is_refused_not_guessed(tmp_path: Path, broken: dict) -> None:
    with pytest.raises(errors.EngineUnavailable):
        service(tmp_path, FakePort(plan(**broken))).get(SID)


def test_missing_anchor_columns_is_an_invalid_plan(tmp_path: Path) -> None:
    body = plan()
    del body["anchor_columns"]
    with pytest.raises(errors.EngineUnavailable):
        service(tmp_path, FakePort(body)).get(SID)


def test_unknown_id_makes_no_engine_call(tmp_path: Path) -> None:
    port = FakePort(plan())
    with pytest.raises(errors.StrategyInstanceNotFound):
        service(tmp_path, port).get("0" * 24)
    assert port.calls == []


def test_duplicate_identity_is_not_found(tmp_path: Path) -> None:
    port = FakePort(plan())
    write_spec(tmp_path)
    (tmp_path / "b.json").write_text((tmp_path / "a.json").read_text())
    svc = StrategyChartLayersService(
        load_snapshot=FilesystemDeploymentCatalog(tmp_path).load_snapshot, feature_plan=port
    )
    with pytest.raises(errors.StrategyInstanceNotFound):
        svc.get(SID)
    assert port.calls == []


def test_unreadable_catalog_is_refused(tmp_path: Path) -> None:
    def broken() -> object:
        raise DeploymentCatalogUnavailableError("gone")

    svc = StrategyChartLayersService(load_snapshot=broken, feature_plan=FakePort(plan()))  # type: ignore[arg-type]
    with pytest.raises(errors.CatalogUnavailable):
        svc.get(SID)


@pytest.mark.parametrize(
    "failure",
    [
        StrategyEngineProjectionTimeout("t"),
        StrategyEngineProjectionNetworkFailure("n"),
        StrategyEngineProjectionProtocolError("p"),
        engine_error(500),
        engine_error(503),
        engine_error(404),
    ],
)
def test_engine_failures_are_unavailable(tmp_path: Path, failure: Exception) -> None:
    with pytest.raises(errors.EngineUnavailable):
        service(tmp_path, FakePort(failure)).get(SID)


def test_engine_rejection_passes_code_and_message_through(tmp_path: Path) -> None:
    with pytest.raises(errors.EngineRejected) as raised:
        service(tmp_path, FakePort(engine_error(422, "unknown_component"))).get(SID)
    assert raised.value.status_code == 422
    assert raised.value.engine_code == "unknown_component"
    assert raised.value.engine_message == "m"


def test_a_real_engine_plan_is_understood(tmp_path: Path) -> None:
    """The plan was captured from Strategy Engine's own `POST .../feature-plan` (ema_pullback)."""
    fixture = (
        Path(__file__).parents[3]
        / "contract"
        / "strategy_engine"
        / "fixtures"
        / "feature_plan_ema_pullback_with_episode.json"
    )
    captured = json.loads(fixture.read_text())

    layers = service(tmp_path, FakePort(captured)).get(SID)

    assert [(e.role, e.timeframe, e.period, e.source) for e in layers.ema_stack] == [
        ("fast", "base", 20, "close"),
        ("anchor", "base", 50, "close"),
        ("slow", "base", 200, "close"),
    ]
    assert [(e.episode_ref, dict(e.params)) for e in layers.episodes] == [
        (
            "trend",
            {
                "fast_period": 20,
                "anchor_period": 50,
                "slow_period": 200,
                "window_bars": 24,
                "break_bars": 24,
                "history_bars": 15000,
            },
        )
    ]
