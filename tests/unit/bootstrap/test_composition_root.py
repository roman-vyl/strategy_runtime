"""Guardrail tests for the single production composition-root construction path."""

import inspect
import json
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
    """9.3: the four outbound HTTP clients are constructed only inside
    `build_application`'s composition step, never inside
    `CommittedBarOrchestrator` or `StrategyCycleHandoffBoundary`, and never
    per-request/per-cycle."""
    forbidden_tokens = (
        "httpx",
        "HttpxStrategyEngineLiveEntryAdapter",
        "HttpxStrategyEngineOpenTradeAdapter",
        "HttpxAbiOpenPositionLookupAdapter",
        "HttpxAbiEntryPackageAdapter",
    )
    for source_path in (
        Path("src/strategy_runtime/utility/committed_bar/orchestrator.py"),
        Path("src/strategy_runtime/utility/handoff/boundary.py"),
    ):
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"forbidden token '{token}' found in {source_path}"


def test_build_application_has_no_composition_override_parameter() -> None:
    parameters = inspect.signature(build_application).parameters
    assert "strategy_cycle_handoff" not in parameters
    forbidden_names = {"strategy_cycle_handoff", "handoff", "sink", "override", "test_mode"}
    assert forbidden_names.isdisjoint(parameters)


def test_ready_application_constructs_all_four_outbound_clients_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")
    entry_package_instances = _count_constructions(monkeypatch, "HttpxAbiEntryPackageAdapter")

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is True
    assert len(live_entry_instances) == 1
    assert len(open_trade_instances) == 1
    assert len(open_position_instances) == 1
    assert len(entry_package_instances) == 1
    assert app.state.outbound_http_clients == (
        live_entry_instances[0],
        open_trade_instances[0],
        open_position_instances[0],
        entry_package_instances[0],
    )


def test_two_build_application_calls_each_construct_their_own_four_clients(
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

    app = build_application(_valid_environ(tmp_path))

    assert len(repository_instances) == 1
    assert len(mutex_instances) == 1
    assert orchestrator_kwargs["state_repository"] is repository_instances[0]
    assert orchestrator_kwargs["keyed_mutex_registry"] is mutex_instances[0]
    assert app.state.state_repository is repository_instances[0]
    assert app.state.keyed_mutex_registry is mutex_instances[0]


def test_startup_rollback_closes_already_constructed_clients_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")

    def _raise_on_construction(**_kwargs: object) -> Any:
        raise ValueError("simulated invalid ABI entry-package configuration")

    monkeypatch.setattr(application_module, "HttpxAbiEntryPackageAdapter", _raise_on_construction)

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    assert len(live_entry_instances) == 1
    assert len(open_trade_instances) == 1
    assert len(open_position_instances) == 1
    assert live_entry_instances[0]._client.is_closed
    assert open_trade_instances[0]._client.is_closed
    assert open_position_instances[0]._client.is_closed


def test_shutdown_closes_all_four_clients_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_call_counts: dict[int, int] = {}

    for name in (
        "HttpxStrategyEngineLiveEntryAdapter",
        "HttpxStrategyEngineOpenTradeAdapter",
        "HttpxAbiOpenPositionLookupAdapter",
        "HttpxAbiEntryPackageAdapter",
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
    assert len(close_call_counts) == 4

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

    assert len(close_call_counts) == 4
    assert all(count == 1 for count in close_call_counts.values())


def test_startup_rollback_covers_construction_after_all_four_clients_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollback boundary extends past the four HTTP clients: a failure
    inside `create_http_app(ready=True, ...)` itself -- after all four
    clients, the semantic graph, and the thin sink already exist -- still
    triggers rollback and returns `ready=False`, never a partially assembled
    `ready=True` application."""
    live_entry_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineLiveEntryAdapter")
    open_trade_instances = _count_constructions(monkeypatch, "HttpxStrategyEngineOpenTradeAdapter")
    open_position_instances = _count_constructions(monkeypatch, "HttpxAbiOpenPositionLookupAdapter")
    entry_package_instances = _count_constructions(monkeypatch, "HttpxAbiEntryPackageAdapter")

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
    ):
        assert len(instances) == 1
        assert instances[0]._client.is_closed


def test_default_sink_dispatches_into_the_real_strategy_runtime_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_environ(tmp_path)
    _write_deployment(tmp_path / "specs" / "selected.json")

    process_calls: list[StrategyBarProcessingUnit[object]] = []
    real_process = StrategyRuntimeOrchestrator.process

    def _recording_process(
        self: StrategyRuntimeOrchestrator, unit: StrategyBarProcessingUnit[object]
    ) -> object:
        process_calls.append(unit)
        return real_process(self, unit)

    monkeypatch.setattr(StrategyRuntimeOrchestrator, "process", _recording_process)

    app = build_application(env)
    assert app.state.ready is True

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )

    assert response.status_code == 200
    assert len(process_calls) == 1
    assert process_calls[0].deployment.source_path == "selected.json"
