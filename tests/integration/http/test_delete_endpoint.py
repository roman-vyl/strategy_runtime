"""HTTP integration tests for DELETE /v1/strategy-instances/{id}."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.enabled_control import errors as shared
from strategy_runtime.runtime.strategy_delete import errors
from strategy_runtime.runtime.strategy_delete.models import DeleteResult
from strategy_runtime.utility.deployment_catalog import (
    DeploymentTrashMover,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

RAW_SPEC = {"anchor": 500}
SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec=RAW_SPEC
)
PATH = f"/v1/strategy-instances/{SID}"


class RecordingLogger:
    def info(self, message: str, *args: object, **kwargs: object) -> None: ...

    def exception(self, message: str, *args: object, **kwargs: object) -> None: ...

    def error(self, message: str, **kwargs: object) -> None: ...

    def warning(self, message: str, **kwargs: object) -> None: ...


def client(deleter: Callable[[str], DeleteResult] | None, *, ready: bool = True) -> TestClient:
    app = create_http_app(
        ready=ready,
        committed_bar_intake=None,
        process_first_fill=None,
        delete_strategy=deleter,
        logger=RecordingLogger(),  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_success_passes_the_id_and_returns_the_result() -> None:
    calls: list[str] = []

    def deleter(sid: str) -> DeleteResult:
        calls.append(sid)
        return DeleteResult(sid, True, ".deleted/a.json")

    response = client(deleter).delete(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "strategy_instance_id": SID,
        "deleted": True,
        "cancelled_entry_order": True,
        "trash_file": ".deleted/a.json",
    }
    assert calls == [SID]


@pytest.mark.parametrize(
    "refusal",
    [
        shared.StrategyInstanceNotFound,
        errors.StillEnabled,
        shared.PositionOpen,
        shared.RecoveryPending,
        shared.CycleNotSettled,
        shared.CancelNotConfirmed,
        shared.FileChanged,
        shared.AbiUnavailable,
        shared.InstanceBusy,
        shared.CatalogUnavailable,
        errors.TrashNameTaken,
        errors.MoveFailed,
    ],
)
def test_refusals_map_to_their_status_and_reason(
    refusal: type[shared.EnabledControlRefused],
) -> None:
    def deleter(sid: str) -> DeleteResult:
        raise refusal

    response = client(deleter).delete(PATH)

    assert response.status_code == refusal.status_code
    assert response.json() == {"status": "delete_refused", "reason": refusal.reason}


def test_not_ready_is_503_and_deletes_nothing() -> None:
    calls: list[str] = []

    def deleter(sid: str) -> DeleteResult:
        calls.append(sid)
        return DeleteResult(sid, False, "x")

    for http in (client(deleter, ready=False), client(None)):
        response = http.delete(PATH)
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
    assert calls == []


def test_unexpected_error_is_500_internal_error() -> None:
    def deleter(sid: str) -> DeleteResult:
        raise RuntimeError("boom")

    response = client(deleter).delete(PATH)

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


def test_end_to_end_disabled_file_moves_to_trash_and_leaves_the_list(tmp_path: Path) -> None:
    from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
    from strategy_runtime.runtime.enabled_control.cancel_step import EntryOrderCancelStep
    from strategy_runtime.runtime.state.repository import (
        InMemoryStrategyInstanceRuntimeStateRepository,
    )
    from strategy_runtime.runtime.strategy_delete.service import StrategyDeleteService

    def write(enabled: bool) -> Path:
        path = tmp_path / "a.json"
        path.write_text(
            json.dumps(
                {
                    "enabled": enabled,
                    "ticker": "BTCUSDT.P",
                    "base_timeframe": "5m",
                    "strategy_id": "ema_pullback",
                    "raw_spec": RAW_SPEC,
                }
            ),
            encoding="utf-8",
        )
        return path

    class Unused:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"{name} must not be used")

    catalog = FilesystemDeploymentCatalog(tmp_path)
    service = StrategyDeleteService(
        load_snapshot=catalog.load_snapshot,
        trash_mover=DeploymentTrashMover(catalog, tmp_path),
        cancel_step=EntryOrderCancelStep(
            state_repository=InMemoryStrategyInstanceRuntimeStateRepository(),
            open_position_resolver=Unused(),  # type: ignore[arg-type]
            abi_entry_cycle_recovery=Unused(),  # type: ignore[arg-type]
        ),
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
    )
    http = TestClient(
        create_http_app(
            ready=True,
            committed_bar_intake=None,
            process_first_fill=None,
            load_deployment_catalog=catalog.load_snapshot,
            delete_strategy=service.delete,
            logger=RecordingLogger(),  # type: ignore[arg-type]
        )
    )

    path = write(True)
    refused = http.delete(PATH)
    assert refused.status_code == 409
    assert refused.json() == {"status": "delete_refused", "reason": "still_enabled"}
    assert path.exists()

    write(False)
    response = http.delete(PATH)

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["cancelled_entry_order"] is False
    assert not path.exists()
    assert len(list((tmp_path / ".deleted").iterdir())) == 1
    assert http.get("/v1/strategy-instances").json()["strategy_instances"] == []
    assert http.delete(PATH).status_code == 404
