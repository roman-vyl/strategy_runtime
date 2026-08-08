"""Composition-root guardrail tests for the first-fill wiring: exactly one
AbiExecutionEventOrchestrator, sharing the same repository/mutex-registry
instances as StrategyRuntimeOrchestrator, connected to create_http_app only
for a ready application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import strategy_runtime.bootstrap.application as application_module
from strategy_runtime.bootstrap.application import build_application


def _valid_environ(tmp_path: Path) -> dict[str, str]:
    specs_path = tmp_path / "specs"
    specs_path.mkdir(exist_ok=True)
    return {
        "RUNTIME_SPECS_PATH": str(specs_path),
        "RUNTIME_JOURNAL_PATH": str(tmp_path / "journal" / "runtime.jsonl"),
        "RUNTIME_STRATEGY_ENGINE_BASE_URL": "http://engine.invalid",
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_BASE_URL": "http://abi.invalid",
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS": "5",
        "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": "256",
    }


def _count_constructions(monkeypatch: pytest.MonkeyPatch, name: str) -> list[Any]:
    real = getattr(application_module, name)
    instances: list[Any] = []

    def wrapper(*args: object, **kwargs: object) -> Any:
        instance = real(*args, **kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr(application_module, name, wrapper)
    return instances


def _record_kwargs(monkeypatch: pytest.MonkeyPatch, name: str) -> dict[str, object]:
    real = getattr(application_module, name)
    recorded: dict[str, object] = {}

    def wrapper(*args: object, **kwargs: object) -> Any:
        recorded.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(application_module, name, wrapper)
    return recorded


# ---------------------------------------------------------------------------
# 6.1 / 6.2 / 6.3 / 6.4
# ---------------------------------------------------------------------------


def test_orchestrator_constructed_once_over_the_exact_shared_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_instances = _count_constructions(
        monkeypatch, "InMemoryStrategyInstanceRuntimeStateRepository"
    )
    mutex_instances = _count_constructions(monkeypatch, "StrategyInstanceKeyedMutexRegistry")
    abi_orchestrator_instances = _count_constructions(monkeypatch, "AbiExecutionEventOrchestrator")
    abi_orchestrator_kwargs = _record_kwargs(monkeypatch, "AbiExecutionEventOrchestrator")
    runtime_orchestrator_kwargs = _record_kwargs(monkeypatch, "StrategyRuntimeOrchestrator")

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is True
    assert len(repository_instances) == 1
    assert len(mutex_instances) == 1
    assert len(abi_orchestrator_instances) == 1

    assert abi_orchestrator_kwargs["state_repository"] is repository_instances[0]
    assert abi_orchestrator_kwargs["keyed_mutex_registry"] is mutex_instances[0]

    # Cross-orchestrator identity: both writers share the same two objects.
    assert (
        abi_orchestrator_kwargs["state_repository"]
        is runtime_orchestrator_kwargs["state_repository"]
    )
    assert (
        abi_orchestrator_kwargs["keyed_mutex_registry"]
        is runtime_orchestrator_kwargs["keyed_mutex_registry"]
    )


# ---------------------------------------------------------------------------
# 6.5 / 6.6: ready gets a connected callable, not-ready gets None
# ---------------------------------------------------------------------------


def test_ready_application_has_connected_first_fill_callable(tmp_path: Path) -> None:
    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is True
    assert app.state.process_first_fill is not None
    assert callable(app.state.process_first_fill)


def test_not_ready_application_has_no_first_fill_callable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        application_module,
        "HttpxAbiEntryPackageAdapter",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("simulated invalid config")),
    )

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    assert app.state.process_first_fill is None

    client = TestClient(app, raise_server_exceptions=False)
    response = client.put(
        "/v1/strategy-instances/instance-a/trade-cycles/cycle-1/first-fill",
        json={"first_fill_at_ms": 1},
    )
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_first_fill_wiring_does_not_change_existing_shutdown_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_call_counts: dict[int, int] = {}

    for name in (
        "HttpxStrategyEngineLiveEntryAdapter",
        "HttpxStrategyEngineOpenTradeAdapter",
        "HttpxAbiOpenPositionLookupAdapter",
        "HttpxAbiEntryPackageAdapter",
        "HttpxAbiPositionManagementAdapter",
    ):
        real = getattr(application_module, name)

        def _make_wrapper(real_cls: Any) -> Any:
            def wrapper(*args: object, **kwargs: object) -> Any:
                instance = real_cls(*args, **kwargs)
                close_call_counts[id(instance)] = 0
                real_close = instance.close

                def counting_close() -> None:
                    close_call_counts[id(instance)] += 1
                    real_close()

                instance.close = counting_close
                return instance

            return wrapper

        monkeypatch.setattr(application_module, name, _make_wrapper(real))

    app = build_application(_valid_environ(tmp_path))
    assert app.state.ready is True
    assert len(close_call_counts) == 5

    with TestClient(app):
        assert all(count == 0 for count in close_call_counts.values())

    assert all(count == 1 for count in close_call_counts.values())


# ---------------------------------------------------------------------------
# 6.9: a forced construction/wiring failure still fails closed
# ---------------------------------------------------------------------------


def test_forced_orchestrator_construction_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")
    entry_package_instances = _count_constructions(monkeypatch, "HttpxAbiEntryPackageAdapter")
    position_management_instances = _count_constructions(
        monkeypatch, "HttpxAbiPositionManagementAdapter"
    )

    def _raise_on_construction(**_kwargs: object) -> Any:
        raise RuntimeError("simulated AbiExecutionEventOrchestrator construction failure")

    monkeypatch.setattr(application_module, "AbiExecutionEventOrchestrator", _raise_on_construction)

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    assert app.state.process_first_fill is None
    for instances in (
        live_entry_instances,
        open_trade_instances,
        open_position_instances,
        entry_package_instances,
        position_management_instances,
    ):
        assert len(instances) == 1
        assert instances[0]._client.is_closed


def test_forced_wiring_failure_leaves_no_partially_wired_ready_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after AbiExecutionEventOrchestrator already exists (e.g.
    inside create_http_app assembly) still yields ready=False, not a ready
    app missing its first-fill callable."""
    real_create_http_app = application_module.create_http_app

    def _create_http_app_wrapper(*, ready: bool, **kwargs: object) -> Any:
        if ready:
            raise RuntimeError("simulated failure while assembling the ready FastAPI application")
        return real_create_http_app(ready=ready, **kwargs)

    monkeypatch.setattr(application_module, "create_http_app", _create_http_app_wrapper)

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    assert app.state.process_first_fill is None


def test_default_first_fill_wiring_dispatches_into_the_real_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from strategy_runtime.runtime.abi_execution_event.orchestrator import (
        AbiExecutionEventOrchestrator,
    )

    process_calls: list[object] = []
    real_process = AbiExecutionEventOrchestrator.process

    def _recording_process(self: AbiExecutionEventOrchestrator, event: object) -> object:
        process_calls.append(event)
        return real_process(self, event)

    monkeypatch.setattr(AbiExecutionEventOrchestrator, "process", _recording_process)

    app = build_application(_valid_environ(tmp_path))
    assert app.state.ready is True

    client = TestClient(app, raise_server_exceptions=False)
    response = client.put(
        "/v1/strategy-instances/instance-a/trade-cycles/cycle-1/first-fill",
        json={"first_fill_at_ms": 1},
    )
    assert response.status_code == 404
    assert len(process_calls) == 1
