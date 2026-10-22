"""HTTP integration tests for PUT /v1/strategy-instances/{id}/enabled."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.enabled_control import errors
from strategy_runtime.runtime.enabled_control.models import EnabledChangeResult
from strategy_runtime.utility.deployment_catalog import (
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

RAW_SPEC = {"anchor": 500}
SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec=RAW_SPEC
)
PATH = f"/v1/strategy-instances/{SID}/enabled"


class RecordingLogger:
    def __init__(self) -> None:
        self.exception_calls: list[str] = []

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self.exception_calls.append(message)

    def error(self, message: str, **kwargs: object) -> None: ...

    def warning(self, message: str, **kwargs: object) -> None: ...


def client(
    setter: Callable[[str, bool], EnabledChangeResult] | None, *, ready: bool = True
) -> TestClient:
    app = create_http_app(
        ready=ready,
        committed_bar_intake=None,
        process_first_fill=None,
        set_strategy_enabled=setter,
        logger=RecordingLogger(),  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_success_passes_id_and_value_and_returns_the_result() -> None:
    calls: list[tuple[str, bool]] = []

    def setter(sid: str, enabled: bool) -> EnabledChangeResult:
        calls.append((sid, enabled))
        return EnabledChangeResult(sid, enabled, True)

    response = client(setter).put(PATH, json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {
        "strategy_instance_id": SID,
        "enabled": False,
        "cancelled_entry_order": True,
    }
    assert calls == [(SID, False)]


@pytest.mark.parametrize(
    "refusal",
    [
        errors.StrategyInstanceNotFound,
        errors.PositionOpen,
        errors.RecoveryPending,
        errors.CycleNotSettled,
        errors.CancelNotConfirmed,
        errors.FileChanged,
        errors.AbiUnavailable,
        errors.InstanceBusy,
        errors.WriteFailed,
        errors.IdentityChanged,
        errors.CatalogUnavailable,
    ],
)
def test_refusals_map_to_their_status_and_reason(
    refusal: type[errors.EnabledControlRefused],
) -> None:
    def setter(sid: str, enabled: bool) -> EnabledChangeResult:
        raise refusal

    response = client(setter).put(PATH, json={"enabled": False})

    assert response.status_code == refusal.status_code
    assert response.json() == {"status": "enabled_change_refused", "reason": refusal.reason}


@pytest.mark.parametrize(
    "body",
    [{}, {"enabled": "true"}, {"enabled": 1}, {"enabled": None}, {"enabled": True, "x": 1}],
)
def test_bad_bodies_are_rejected_and_change_nothing(body: dict[str, object]) -> None:
    calls: list[tuple[str, bool]] = []

    def setter(sid: str, enabled: bool) -> EnabledChangeResult:
        calls.append((sid, enabled))
        return EnabledChangeResult(sid, enabled, False)

    response = client(setter).put(PATH, json=body)

    assert response.status_code == 400
    assert calls == []


def test_not_ready_is_503_and_changes_nothing() -> None:
    calls: list[tuple[str, bool]] = []

    def setter(sid: str, enabled: bool) -> EnabledChangeResult:
        calls.append((sid, enabled))
        return EnabledChangeResult(sid, enabled, False)

    assert client(setter, ready=False).put(PATH, json={"enabled": True}).status_code == 503
    assert client(None).put(PATH, json={"enabled": True}).status_code == 503
    assert calls == []


def test_unexpected_error_is_500_internal_error() -> None:
    def setter(sid: str, enabled: bool) -> EnabledChangeResult:
        raise RuntimeError("boom")

    response = client(setter).put(PATH, json={"enabled": True})

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


def test_end_to_end_with_files_the_next_list_shows_the_new_value(tmp_path: Path) -> None:
    from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
    from strategy_runtime.runtime.enabled_control.service import StrategyEnabledControlService
    from strategy_runtime.runtime.state.repository import (
        InMemoryStrategyInstanceRuntimeStateRepository,
    )
    from strategy_runtime.utility.deployment_catalog import DeploymentEnabledFileWriter

    path = tmp_path / "a.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "ticker": "BTCUSDT.P",
                "base_timeframe": "5m",
                "strategy_id": "ema_pullback",
                "raw_spec": RAW_SPEC,
            }
        ),
        encoding="utf-8",
    )
    catalog = FilesystemDeploymentCatalog(tmp_path)

    class Unused:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"{name} must not be used")

    service = StrategyEnabledControlService(
        load_snapshot=catalog.load_snapshot,
        enabled_writer=DeploymentEnabledFileWriter(catalog, tmp_path),
        state_repository=InMemoryStrategyInstanceRuntimeStateRepository(),
        open_position_resolver=Unused(),  # type: ignore[arg-type]
        abi_entry_cycle_recovery=Unused(),  # type: ignore[arg-type]
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
    )
    app = create_http_app(
        ready=True,
        committed_bar_intake=None,
        process_first_fill=None,
        load_deployment_catalog=catalog.load_snapshot,
        set_strategy_enabled=service.set_enabled,
        logger=RecordingLogger(),  # type: ignore[arg-type]
    )
    http = TestClient(app)

    response = http.put(PATH, json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["cancelled_entry_order"] is False
    listed = http.get("/v1/strategy-instances").json()["strategy_instances"]
    assert [item["enabled"] for item in listed] == [False]
    assert http.put(PATH, json={"enabled": True}).json()["enabled"] is True
    assert (
        http.put(
            "/v1/strategy-instances/ema_pullback:nope/enabled", json={"enabled": True}
        ).status_code
        == 404
    )
