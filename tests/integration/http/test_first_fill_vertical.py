"""Vertical Runtime test: real repository, real mutex registry, real
AbiExecutionEventOrchestrator, driven through the real HTTP first-fill
route -- no fakes below the HTTP boundary, no real ABI or Strategy Engine
server."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.abi_execution_event.orchestrator import (
    AbiExecutionEventOrchestrator,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)

_SID = "instance-a"
_TRADE_CYCLE_ID = "cycle-1"
_SOURCE_PLAN_BAR_OPEN_TIME_MS = 900_000
_FIRST_FILL_AT_MS = 905_000


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", _SOURCE_PLAN_BAR_OPEN_TIME_MS, "100", "99", "103", "runner")


def _seed_repository() -> InMemoryStrategyInstanceRuntimeStateRepository:
    repo = InMemoryStrategyInstanceRuntimeStateRepository()
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=_SID,
        strategy_id="strategy-x",
        instrument="BTCUSDT.P",
        base_timeframe="15m",
        raw_spec={},
        source_path="a.json",
    )
    base_state = repo.get_or_create(request)
    with_cycle = replace(
        base_state,
        current_trade_cycle=CurrentTradeCycle(
            _TRADE_CYCLE_ID, AppliedEntryPackage(_desired_entry(), "0.01")
        ),
    )
    repo.save(with_cycle)
    return repo


def _make_vertical_client() -> tuple[TestClient, InMemoryStrategyInstanceRuntimeStateRepository]:
    repo = _seed_repository()
    orchestrator = AbiExecutionEventOrchestrator(
        state_repository=repo,
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
    )
    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        committed_bar_intake=None,
        process_first_fill=orchestrator.process,
    )
    return TestClient(app, raise_server_exceptions=False), repo


def _url() -> str:
    return f"/v1/strategy-instances/{_SID}/trade-cycles/{_TRADE_CYCLE_ID}/first-fill"


def test_first_put_applies_and_persists_the_frozen_entry_context() -> None:
    client, repo = _make_vertical_client()

    response = client.put(_url(), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})

    assert response.status_code == 200
    assert response.json() == {"status": "first_fill_recorded"}

    stored = repo.get(_SID)
    assert stored is not None
    assert stored.current_trade_cycle is not None
    context = stored.current_trade_cycle.frozen_entry_context
    assert context is not None
    applied_entry = stored.current_trade_cycle.applied_entry_package.applied_desired_entry
    assert context.desired_entry == applied_entry
    assert context.first_fill_at_ms == _FIRST_FILL_AT_MS
    assert context.entry_bar_open_time_ms == _SOURCE_PLAN_BAR_OPEN_TIME_MS


def test_identical_retry_returns_200_and_leaves_the_frozen_context_unchanged() -> None:
    client, repo = _make_vertical_client()

    first = client.put(_url(), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})
    assert first.status_code == 200
    first_context = repo.get(_SID).current_trade_cycle.frozen_entry_context

    save_calls: list[object] = []
    original_save = repo.save

    def _counting_save(state: object) -> object:
        save_calls.append(state)
        return original_save(state)

    repo.save = _counting_save  # type: ignore[method-assign]

    second = client.put(_url(), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})

    assert second.status_code == 200
    assert second.json() == first.json() == {"status": "first_fill_recorded"}
    assert repo.get(_SID).current_trade_cycle.frozen_entry_context == first_context
    assert save_calls == []


def test_conflicting_retry_returns_409_and_leaves_state_unchanged() -> None:
    client, repo = _make_vertical_client()

    first = client.put(_url(), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})
    assert first.status_code == 200
    frozen_before = repo.get(_SID).current_trade_cycle.frozen_entry_context

    conflicting = client.put(_url(), json={"first_fill_at_ms": _FIRST_FILL_AT_MS + 1_000})

    assert conflicting.status_code == 409
    assert conflicting.json() == {"status": "first_fill_conflict"}
    assert repo.get(_SID).current_trade_cycle.frozen_entry_context == frozen_before
