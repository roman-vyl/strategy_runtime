"""HTTP integration tests for the close-position and cancel-entry-orders commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.enabled_control import errors
from strategy_runtime.runtime.operator_commands import (
    CancelEntryOrdersResult,
    ClosePositionResult,
    NoPosition,
)
from strategy_runtime.utility.deployment_catalog import derive_strategy_instance_id

SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec={"anchor": 500}
)
CLOSE = f"/v1/strategy-instances/{SID}/close-position"
CANCEL = f"/v1/strategy-instances/{SID}/cancel-entry-orders"


class RecordingLogger:
    def exception(self, message: str, *args: object, **kwargs: object) -> None: ...

    def error(self, message: str, **kwargs: object) -> None: ...

    def warning(self, message: str, **kwargs: object) -> None: ...


def client(
    *,
    close: Callable[[str], ClosePositionResult] | None = None,
    cancel: Callable[[str], CancelEntryOrdersResult] | None = None,
    ready: bool = True,
) -> TestClient:
    app = create_http_app(
        ready=ready,
        committed_bar_intake=None,
        process_first_fill=None,
        close_position=close,
        cancel_entry_orders=cancel,
        logger=RecordingLogger(),  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_close_success_returns_the_result() -> None:
    calls: list[str] = []

    def close(sid: str) -> ClosePositionResult:
        calls.append(sid)
        return ClosePositionResult(sid, "cycle-1", False, "runtime_signal")

    response = client(close=close).post(CLOSE)

    assert response.status_code == 200
    assert response.json() == {
        "strategy_instance_id": SID,
        "trade_cycle_id": "cycle-1",
        "enabled": False,
        "closure_reason": "runtime_signal",
    }
    assert calls == [SID]


def test_cancel_success_returns_the_result() -> None:
    response = client(
        cancel=lambda sid: CancelEntryOrdersResult(sid, False, True),
    ).post(CANCEL)

    assert response.status_code == 200
    assert response.json() == {
        "strategy_instance_id": SID,
        "enabled": False,
        "cancelled_entry_order": True,
    }


@pytest.mark.parametrize(
    "refusal",
    [
        NoPosition,
        errors.StrategyInstanceNotFound,
        errors.RecoveryPending,
        errors.CycleNotSettled,
        errors.PositionOpen,
        errors.CancelNotConfirmed,
        errors.FileChanged,
        errors.AbiUnavailable,
        errors.InstanceBusy,
        errors.WriteFailed,
        errors.CatalogUnavailable,
    ],
)
@pytest.mark.parametrize("path", [CLOSE, CANCEL])
def test_refusals_map_to_their_status_and_reason(
    path: str, refusal: type[errors.EnabledControlRefused]
) -> None:
    def fail(sid: str) -> Any:
        raise refusal

    response = client(close=fail, cancel=fail).post(path)

    assert response.status_code == refusal.status_code
    assert response.json() == {"status": "enabled_change_refused", "reason": refusal.reason}


@pytest.mark.parametrize("path", [CLOSE, CANCEL])
def test_not_ready_is_503(path: str) -> None:
    assert client(ready=False, close=lambda s: 1, cancel=lambda s: 1).post(path).status_code == 503  # type: ignore[arg-type,return-value]
    assert client().post(path).status_code == 503


@pytest.mark.parametrize("path", [CLOSE, CANCEL])
def test_unexpected_error_is_500(path: str) -> None:
    def boom(sid: str) -> Any:
        raise RuntimeError("boom")

    response = client(close=boom, cancel=boom).post(path)

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


@pytest.mark.parametrize("path", [CLOSE, CANCEL])
@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_other_methods_are_405(path: str, method: str) -> None:
    assert getattr(client(), method)(path).status_code == 405
