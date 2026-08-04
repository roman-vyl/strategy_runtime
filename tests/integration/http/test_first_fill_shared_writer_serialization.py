"""Shared-writer serialization test: one real StrategyInstanceKeyedMutexRegistry
and one real repository, proving the first-fill HTTP path and a closed-bar
writer serialize per strategy_instance_id through the shared mutex, and that
two different instance keys never block each other. No real ABI or Strategy
Engine server is started."""

from __future__ import annotations

import threading
import time
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
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)

_SID_A = "instance-a"
_SID_B = "instance-b"
_TRADE_CYCLE_ID = "cycle-1"
_SOURCE_PLAN_BAR_OPEN_TIME_MS = 900_000
_FIRST_FILL_AT_MS = 905_000


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", _SOURCE_PLAN_BAR_OPEN_TIME_MS, "100", "99", "103", "runner")


class _RecordingRepository:
    """Wraps a real InMemoryStrategyInstanceRuntimeStateRepository, recording
    every get(...) call by strategy_instance_id."""

    def __init__(self, inner: InMemoryStrategyInstanceRuntimeStateRepository) -> None:
        self._inner = inner
        self.get_calls: list[str] = []
        self._get_calls_lock = threading.Lock()

    def get_or_create(self, request: object) -> StrategyInstanceRuntimeState:
        return self._inner.get_or_create(request)  # type: ignore[arg-type]

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        with self._get_calls_lock:
            self.get_calls.append(strategy_instance_id)
        return self._inner.get(strategy_instance_id)

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        return self._inner.save(state)


def _seed(repo: InMemoryStrategyInstanceRuntimeStateRepository, sid: str) -> None:
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=sid,
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


def _url(sid: str) -> str:
    return f"/v1/strategy-instances/{sid}/trade-cycles/{_TRADE_CYCLE_ID}/first-fill"


def _make_harness() -> tuple[TestClient, _RecordingRepository, StrategyInstanceKeyedMutexRegistry]:
    inner_repo = InMemoryStrategyInstanceRuntimeStateRepository()
    _seed(inner_repo, _SID_A)
    _seed(inner_repo, _SID_B)
    repo = _RecordingRepository(inner_repo)
    registry = StrategyInstanceKeyedMutexRegistry()
    orchestrator = AbiExecutionEventOrchestrator(
        state_repository=repo,  # type: ignore[arg-type]
        keyed_mutex_registry=registry,
    )
    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        process_committed_bar=None,
        process_first_fill=orchestrator.process,
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, repo, registry


def test_first_fill_path_waits_for_a_held_closed_bar_writer_then_loads_fresh_state() -> None:
    client, repo, registry = _make_harness()

    writer_holds = threading.Event()
    release_writer = threading.Event()

    def closed_bar_writer() -> None:
        with registry.hold(_SID_A):
            # Simulate closed-bar-writer work under the lock: mutate a
            # harmless field before the first-fill path is ever allowed in.
            current = repo.get(_SID_A)
            assert current is not None
            repo.save(replace(current, risk_multiplier="2"))
            writer_holds.set()
            release_writer.wait(timeout=5)

    writer_thread = threading.Thread(target=closed_bar_writer)
    writer_thread.start()
    assert writer_holds.wait(timeout=2), "closed-bar writer never acquired the mutex"
    repo.get_calls.clear()  # drop the writer's own get(...) call from the count below

    result: dict[str, object] = {}

    def do_put() -> None:
        result["response"] = client.put(_url(_SID_A), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})

    put_thread = threading.Thread(target=do_put)
    put_thread.start()

    # While the writer holds instance-A's mutex, the first-fill path must
    # not have reached repo.get(...) for instance-A yet.
    time.sleep(0.2)
    assert repo.get_calls == []

    release_writer.set()
    writer_thread.join(timeout=5)
    put_thread.join(timeout=5)

    response = result["response"]
    assert response.status_code == 200  # type: ignore[union-attr]
    assert repo.get_calls == [_SID_A]

    # Fresh-state visibility: the writer's pre-release mutation is what the
    # first-fill path saw and persisted forward.
    stored = repo.get(_SID_A)
    assert stored is not None
    assert stored.risk_multiplier == "2"


def test_instance_b_first_fill_is_not_blocked_while_instance_a_mutex_is_held() -> None:
    client, repo, registry = _make_harness()

    writer_holds = threading.Event()
    release_writer = threading.Event()

    def closed_bar_writer() -> None:
        with registry.hold(_SID_A):
            writer_holds.set()
            release_writer.wait(timeout=5)

    writer_thread = threading.Thread(target=closed_bar_writer)
    writer_thread.start()
    assert writer_holds.wait(timeout=2), "closed-bar writer never acquired the mutex"

    try:
        response = client.put(_url(_SID_B), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})
    finally:
        release_writer.set()
        writer_thread.join(timeout=5)

    assert response.status_code == 200
    assert repo.get_calls == [_SID_B]
