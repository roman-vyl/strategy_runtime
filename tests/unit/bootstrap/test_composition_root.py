"""Guardrail tests for the single production composition-root construction path."""

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import strategy_runtime.bootstrap.application as application_module
from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.utility.committed_bar.models import StrategyBarProcessingUnit


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


def _write_deployment(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "ticker": "BTCUSDT.P",
                "base_timeframe": "5m",
                "strategy_id": "ema_pullback",
                "raw_spec": {"direction": {"fast_ema": 20, "anchor_ema": 200}},
            }
        ),
        encoding="utf-8",
    )


def _count_constructions(monkeypatch: pytest.MonkeyPatch, name: str) -> list[Any]:
    """Wrap `strategy_runtime.bootstrap.application.<name>` and record every instance."""
    real = getattr(application_module, name)
    instances: list[Any] = []

    def wrapper(*args: object, **kwargs: object) -> Any:
        instance = real(*args, **kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr(application_module, name, wrapper)
    return instances


def _record_kwargs(monkeypatch: pytest.MonkeyPatch, name: str) -> dict[str, object]:
    """Wrap `strategy_runtime.bootstrap.application.<name>` and record its kwargs."""
    real = getattr(application_module, name)
    recorded: dict[str, object] = {}

    def wrapper(*args: object, **kwargs: object) -> Any:
        recorded.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(application_module, name, wrapper)
    return recorded


def test_outbound_http_clients_are_not_constructed_by_utility_dispatch_components() -> None:
    """The five outbound HTTP clients are constructed only inside
    `build_application`'s composition step, never inside
    `CommittedBarOrchestrator`, and never per-request/per-cycle."""
    forbidden_tokens = (
        "httpx",
        "HttpxStrategyEngineLiveEntryAdapter",
        "HttpxStrategyEngineOpenTradeAdapter",
        "HttpxAbiOpenPositionLookupAdapter",
        "HttpxAbiEntryPackageAdapter",
        "HttpxAbiPositionManagementAdapter",
    )
    source_path = Path("src/strategy_runtime/utility/committed_bar/orchestrator.py")
    source = source_path.read_text(encoding="utf-8")
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in {source_path}"


def test_runtime_orchestrator_is_the_direct_strategy_cycle_dispatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_orchestrators = _count_constructions(monkeypatch, "StrategyRuntimeOrchestrator")
    committed_bar_kwargs = _record_kwargs(monkeypatch, "CommittedBarOrchestrator")

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is True
    assert len(runtime_orchestrators) == 1
    assert committed_bar_kwargs["strategy_cycle_dispatcher"] is runtime_orchestrators[0]


def test_ready_application_constructs_all_five_outbound_clients_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")
    entry_package_instances = _count_constructions(monkeypatch, "HttpxAbiEntryPackageAdapter")
    position_management_instances = _count_constructions(
        monkeypatch, "HttpxAbiPositionManagementAdapter"
    )

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is True
    assert len(live_entry_instances) == 1
    assert len(open_trade_instances) == 1
    assert len(open_position_instances) == 1
    assert len(entry_package_instances) == 1
    assert len(position_management_instances) == 1
    assert app.state.outbound_http_clients == (
        live_entry_instances[0],
        open_trade_instances[0],
        open_position_instances[0],
        entry_package_instances[0],
        position_management_instances[0],
    )


def test_two_build_application_calls_each_construct_their_own_five_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")

    build_application(_valid_environ(tmp_path))
    build_application(_valid_environ(tmp_path))

    assert len(live_entry_instances) == 2
    assert live_entry_instances[0] is not live_entry_instances[1]


def test_shares_single_repository_and_mutex_registry_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_instances = _count_constructions(
        monkeypatch, "InMemoryStrategyInstanceRuntimeStateRepository"
    )
    mutex_instances = _count_constructions(monkeypatch, "StrategyInstanceKeyedMutexRegistry")
    orchestrator_kwargs = _record_kwargs(monkeypatch, "StrategyRuntimeOrchestrator")
    position_management_instances = _count_constructions(
        monkeypatch, "PositionManagementOrchestrator"
    )

    app = build_application(_valid_environ(tmp_path))

    assert len(repository_instances) == 1
    assert len(mutex_instances) == 1
    assert orchestrator_kwargs["state_repository"] is repository_instances[0]
    assert orchestrator_kwargs["keyed_mutex_registry"] is mutex_instances[0]
    assert (
        orchestrator_kwargs["position_management_orchestrator"] is position_management_instances[0]
    )
    assert app.state.state_repository is repository_instances[0]
    assert app.state.keyed_mutex_registry is mutex_instances[0]


def test_startup_rollback_closes_already_constructed_clients_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")

    entry_package_instances = _count_constructions(monkeypatch, "HttpxAbiEntryPackageAdapter")

    def _raise_on_construction(**_kwargs: object) -> Any:
        raise ValueError("simulated invalid ABI position-management configuration")

    monkeypatch.setattr(
        application_module, "HttpxAbiPositionManagementAdapter", _raise_on_construction
    )

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    assert len(live_entry_instances) == 1
    assert len(open_trade_instances) == 1
    assert len(open_position_instances) == 1
    assert len(entry_package_instances) == 1
    assert live_entry_instances[0]._client.is_closed
    assert open_trade_instances[0]._client.is_closed
    assert open_position_instances[0]._client.is_closed
    assert entry_package_instances[0]._client.is_closed


def test_shutdown_closes_all_five_clients_exactly_once(
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

        def _make_wrapper(real_cls: Callable[..., Any]) -> Callable[..., Any]:
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

    # Repeated close requests are idempotent: calling close_all_once() again,
    # directly or via a second lifespan shutdown, must not double-close.
    app.state.outbound_http_client_lifecycle.close_all_once()
    app.state.outbound_http_client_lifecycle.close_all_once()
    assert all(count == 1 for count in close_call_counts.values())


def test_lifecycle_owner_close_all_once_is_idempotent_when_called_directly(
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

        def _make_wrapper(real_cls: Callable[..., Any]) -> Callable[..., Any]:
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
    lifecycle = app.state.outbound_http_client_lifecycle

    lifecycle.close_all_once()
    lifecycle.close_all_once()
    lifecycle.close_all_once()

    assert len(close_call_counts) == 5
    assert all(count == 1 for count in close_call_counts.values())


def test_startup_rollback_covers_construction_after_all_five_clients_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollback boundary extends past the five HTTP clients: a failure
    inside `create_http_app(ready=True, ...)` itself -- after all five
    clients and the semantic graph already exist -- still
    triggers rollback and returns `ready=False`, never a partially assembled
    `ready=True` application."""
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")
    entry_package_instances = _count_constructions(monkeypatch, "HttpxAbiEntryPackageAdapter")
    position_management_instances = _count_constructions(
        monkeypatch, "HttpxAbiPositionManagementAdapter"
    )

    real_create_http_app = application_module.create_http_app

    def _create_http_app_wrapper(*, ready: bool, **kwargs: object) -> Any:
        if ready:
            raise RuntimeError("simulated failure while assembling the ready FastAPI application")
        return real_create_http_app(ready=ready, **kwargs)

    monkeypatch.setattr(application_module, "create_http_app", _create_http_app_wrapper)

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    for instances in (
        live_entry_instances,
        open_trade_instances,
        open_position_instances,
        entry_package_instances,
        position_management_instances,
    ):
        assert len(instances) == 1
        assert instances[0]._client.is_closed


def test_missing_position_management_timeout_fails_before_any_client_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_environ(tmp_path)
    del env["RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS"]
    construction_counts = [
        _count_constructions(monkeypatch, name)
        for name in (
            "HttpxStrategyEngineLiveEntryAdapter",
            "HttpxStrategyEngineOpenTradeAdapter",
            "HttpxAbiOpenPositionLookupAdapter",
            "HttpxAbiEntryPackageAdapter",
            "HttpxAbiPositionManagementAdapter",
        )
    ]

    app = build_application(env)

    assert app.state.ready is False
    assert all(instances == [] for instances in construction_counts)


def test_default_dispatcher_is_the_real_strategy_runtime_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_environ(tmp_path)
    _write_deployment(tmp_path / "specs" / "selected.json")

    process_calls: list[StrategyBarProcessingUnit[object]] = []
    processed = threading.Event()
    real_process = StrategyRuntimeOrchestrator.process

    def _recording_process(
        self: StrategyRuntimeOrchestrator, unit: StrategyBarProcessingUnit[object]
    ) -> object:
        process_calls.append(unit)
        try:
            return real_process(self, unit)
        finally:
            processed.set()

    monkeypatch.setattr(StrategyRuntimeOrchestrator, "process", _recording_process)

    app = build_application(env)
    assert app.state.ready is True

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/webhooks/closed-bar",
            json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
        )

        assert response.status_code == 200
        assert processed.wait(timeout=5), "intake worker never processed the accepted event"

    assert len(process_calls) == 1
    assert process_calls[0].deployment.source_path == "selected.json"
