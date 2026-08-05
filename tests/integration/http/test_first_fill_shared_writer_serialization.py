"""Shared-writer serialization test: one real StrategyInstanceKeyedMutexRegistry
and one real repository, proving the first-fill HTTP path and a closed-bar
writer serialize per strategy_instance_id through the shared mutex, and that
two different instance keys never block each other. No real ABI or Strategy
Engine server is started."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.abi_execution_event.orchestrator import (
    AbiExecutionEventOrchestrator,
)
from strategy_runtime.runtime.committed_bar_intake import (
    CommittedBarIntakeBoundary,
    CommittedBarIntakeWorker,
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
from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    SelectedDeployment,
    StrategyCycleDispatchOutcome,
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
        committed_bar_intake=None,
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


# ---------------------------------------------------------------------------
# Same coverage, but the "closed-bar writer" is the real production call
# path: HTTP webhook -> CommittedBarIntakeBoundary -> CommittedBarIntakeWorker
# -> CommittedBarOrchestrator -> dispatch, running on the actual intake
# worker thread rather than a hand-rolled stand-in thread.
# ---------------------------------------------------------------------------


class _GatedMutexHoldingDispatcher:
    """Acquire the real keyed-mutex registry for one instance and block on a
    controllable gate -- standing in for the real per-instance critical
    section a strategy cycle would hold."""

    def __init__(
        self,
        registry: StrategyInstanceKeyedMutexRegistry,
        writer_holds: threading.Event,
        release_writer: threading.Event,
    ) -> None:
        self._registry = registry
        self._writer_holds = writer_holds
        self._release_writer = release_writer

    def dispatch(self, unit: object) -> StrategyCycleDispatchOutcome:
        strategy_instance_id = unit.strategy_instance_id  # type: ignore[attr-defined]
        with self._registry.hold(strategy_instance_id):
            self._writer_holds.set()
            assert self._release_writer.wait(timeout=5), "release_writer was never set"
        return StrategyCycleDispatchOutcome.succeeded(strategy_instance_id)


class _SingleDeploymentCatalog:
    def load_snapshot(self) -> None:
        return None


class _FixedTargetSelector:
    def __init__(self, strategy_instance_id: str) -> None:
        self._strategy_instance_id = strategy_instance_id

    def select(
        self, *, event: CommittedBarEvent, snapshot: object
    ) -> tuple[SelectedDeployment[None], ...]:
        return (SelectedDeployment(self._strategy_instance_id, None),)


class _NoOpJournal:
    def orchestration_started(self, **_kwargs: object) -> None: ...
    def orchestration_failed(self, **_kwargs: object) -> None: ...
    def strategy_cycle_outcome(self, **_kwargs: object) -> None: ...
    def orchestration_completed(self, **_kwargs: object) -> None: ...


def _make_full_intake_harness(
    target_sid: str,
) -> tuple[
    TestClient,
    _RecordingRepository,
    CommittedBarIntakeWorker,
    threading.Event,
    threading.Event,
]:
    inner_repo = InMemoryStrategyInstanceRuntimeStateRepository()
    _seed(inner_repo, _SID_A)
    _seed(inner_repo, _SID_B)
    repo = _RecordingRepository(inner_repo)
    registry = StrategyInstanceKeyedMutexRegistry()
    first_fill_orchestrator = AbiExecutionEventOrchestrator(
        state_repository=repo,  # type: ignore[arg-type]
        keyed_mutex_registry=registry,
    )

    writer_holds = threading.Event()
    release_writer = threading.Event()
    committed_bar_orchestrator = CommittedBarOrchestrator(
        deployment_catalog=_SingleDeploymentCatalog(),
        deployment_selector=_FixedTargetSelector(target_sid),
        strategy_cycle_dispatcher=_GatedMutexHoldingDispatcher(
            registry, writer_holds, release_writer
        ),
        processing_journal=_NoOpJournal(),
    )
    intake = CommittedBarIntakeBoundary(capacity=8)
    worker = CommittedBarIntakeWorker(
        intake, committed_bar_orchestrator, logging.getLogger("test.shared_writer")
    )
    worker.start()

    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        committed_bar_intake=intake,
        process_first_fill=first_fill_orchestrator.process,
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, repo, worker, writer_holds, release_writer


def test_first_fill_waits_for_the_real_intake_worker_holding_the_same_instance_mutex() -> None:
    client, repo, worker, writer_holds, release_writer = _make_full_intake_harness(_SID_A)
    try:
        response = client.post(
            "/v1/webhooks/closed-bar",
            json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
        )
        assert response.status_code == 200
        assert writer_holds.wait(timeout=2), "intake worker never acquired the mutex"
        repo.get_calls.clear()  # drop the dispatcher's own activity, if any

        result: dict[str, object] = {}

        def do_put() -> None:
            result["response"] = client.put(
                _url(_SID_A), json={"first_fill_at_ms": _FIRST_FILL_AT_MS}
            )

        put_thread = threading.Thread(target=do_put)
        put_thread.start()

        # While the real intake worker holds instance-A's mutex, the
        # first-fill path must not have reached repo.get(...) yet.
        time.sleep(0.2)
        assert repo.get_calls == []

        release_writer.set()
        put_thread.join(timeout=5)
    finally:
        worker.stop_once()

    response = result["response"]
    assert response.status_code == 200  # type: ignore[union-attr]
    assert repo.get_calls == [_SID_A]


def test_instance_b_first_fill_is_not_blocked_by_the_real_intake_worker_on_instance_a() -> None:
    client, repo, worker, writer_holds, release_writer = _make_full_intake_harness(_SID_A)
    try:
        response = client.post(
            "/v1/webhooks/closed-bar",
            json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
        )
        assert response.status_code == 200
        assert writer_holds.wait(timeout=2), "intake worker never acquired the mutex"

        put_response = client.put(_url(_SID_B), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})
    finally:
        release_writer.set()
        worker.stop_once()

    assert put_response.status_code == 200
    assert repo.get_calls == [_SID_B]
