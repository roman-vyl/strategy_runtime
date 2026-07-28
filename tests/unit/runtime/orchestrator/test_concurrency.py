"""Deterministic same-instance and different-instance concurrency proofs.

Every test below proves its requirement structurally, not by timing:

- Same-instance non-overlap (5.1/5.2) uses a first-arrival gate that blocks the
  lock winner *inside* its critical section (after ``get_or_create`` already
  returned) while the loser races for the real per-key lock. If the mutex
  released early, the loser would reach ``get_or_create`` while the winner is
  still gated; a snapshot taken at that exact instant proves it never does.
- Different-instance overlap (5.3) uses a ``threading.Barrier`` that both
  threads must reach *from inside* their own critical section. If the
  registry wrongly serialized distinct keys, the second thread could never
  reach the barrier and the wait would time out / break the barrier.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation import EntryAppliedConfirmation
from strategy_runtime.runtime.entry_reconciliation_orchestrator.orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupResponse,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.resolver import OpenPositionResolver
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SID_A = "instance-a"
_SID_B = "instance-b"
_TIMEOUT = 5.0


def _request_for(sid: str) -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=sid,
        strategy_id="strategy-x",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="/specs/x.json",
    )


def _make_state(sid: str) -> StrategyInstanceRuntimeState:
    return InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(_request_for(sid))


def _make_unit(sid: str) -> StrategyBarProcessingUnit[DeploymentSpecification]:
    return StrategyBarProcessingUnit(
        strategy_instance_id=sid,
        deployment=DeploymentSpecification(
            strategy_instance_id=sid,
            enabled=True,
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            strategy_id="strategy-x",
            raw_spec={"ema": 200},
            source_path="/specs/x.json",
        ),
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 1000),
    )


class _Abi:
    def __init__(self, response: OpenPositionLookupResponse) -> None:
        self._response = response

    def lookup(self, request: object) -> OpenPositionLookupResponse:
        return self._response


def _resolved(
    state: StrategyInstanceRuntimeState,
) -> PositionResolvedStrategyInstanceRuntimeState:
    return OpenPositionResolver(_Abi(OpenPositionLookupResponse(False))).resolve(state)


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100.00", "99.00", "103.00", "runner")


class _StartBarrieredMutex:
    """Force every caller to rendezvous before racing for the real per-key lock."""

    def __init__(
        self, registry: StrategyInstanceKeyedMutexRegistry, barrier: threading.Barrier
    ) -> None:
        self._registry = registry
        self._barrier = barrier

    def hold(self, sid: str) -> Any:
        self._barrier.wait(timeout=_TIMEOUT)
        return self._registry.hold(sid)


class _EventLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[str] = []

    def record(self, label: str) -> None:
        with self._lock:
            self.events.append(f"{label}:{threading.current_thread().name}")

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self.events)


class _FirstArrivalGate:
    """Block only the first caller to arrive, releasing it on demand."""

    def __init__(self) -> None:
        self._claim_lock = threading.Lock()
        self._claimed = False
        self.first_entered = threading.Event()
        self.first_thread_name: str | None = None
        self._release = threading.Event()

    def arrive(self) -> None:
        with self._claim_lock:
            is_first = not self._claimed
            self._claimed = True
        if is_first:
            self.first_thread_name = threading.current_thread().name
            self.first_entered.set()
            self._release.wait(timeout=_TIMEOUT)

    def release(self) -> None:
        self._release.set()


class _RecordingStatefulRepository:
    """Stateful in-memory-backed repository recording get_or_create/save order."""

    def __init__(self, initial: StrategyInstanceRuntimeState, log: _EventLog) -> None:
        self._backing = InMemoryStrategyInstanceRuntimeStateRepository()
        self._backing.get_or_create(_request_for(initial.strategy_instance_id))
        self._log = log
        self.save_results: list[StrategyInstanceRuntimeState] = []

    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState:
        self._log.record("get_or_create")
        return self._backing.get_or_create(request)

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._backing.get(strategy_instance_id)

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self._log.record("save")
        saved = self._backing.save(state)
        self.save_results.append(saved)
        return saved


class _GatedRecordingResolver:
    """Records resolve calls and its input state; the first caller is gated."""

    def __init__(self, log: _EventLog, gate: _FirstArrivalGate) -> None:
        self._log = log
        self._gate = gate
        self._states_lock = threading.Lock()
        self.received_states: list[StrategyInstanceRuntimeState] = []

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        self._log.record("resolve")
        with self._states_lock:
            self.received_states.append(state)
        self._gate.arrive()
        return _resolved(state)


class _RecordingApplyRouter:
    """Always routes to a live-entry projection carrying a fixed desired entry."""

    def __init__(self, log: _EventLog) -> None:
        self._log = log

    def route(self, item: PositionResolvedStrategyInstance) -> LiveEntryProjectedStrategyInstance:
        self._log.record("route")
        return LiveEntryProjectedStrategyInstance(item, _desired_entry())


class _RecordingExecutionPort:
    def __init__(self, log: _EventLog) -> None:
        self._log = log

    def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
        self._log.record("reconcile")
        return EntryAppliedConfirmation(
            strategy_instance_id=source_state.strategy_instance_id,
            trade_cycle_id=command.trade_cycle_id,
            applied_desired_entry=command.desired_entry,
            calculated_quantity="0.5",
        )


@dataclass
class _SameInstancePairResult:
    winner_name: str
    loser_name: str
    loser_events_before_release: int
    events: list[str]
    resolver_received_states: list[StrategyInstanceRuntimeState]
    save_results: list[StrategyInstanceRuntimeState]
    process_results: list[StrategyInstanceRuntimeState]


def _run_same_instance_pair() -> _SameInstancePairResult:
    state = _make_state(_SID_A)
    unit = _make_unit(_SID_A)
    registry = StrategyInstanceKeyedMutexRegistry()
    start_barrier = threading.Barrier(2, timeout=_TIMEOUT)
    log = _EventLog()
    gate = _FirstArrivalGate()

    repo = _RecordingStatefulRepository(state, log)
    resolver = _GatedRecordingResolver(log, gate)
    router = _RecordingApplyRouter(log)
    execution_port = _RecordingExecutionPort(log)

    orch = StrategyRuntimeOrchestrator(
        state_repository=repo,
        open_position_resolver=resolver,
        use_case_router=router,
        keyed_mutex_registry=_StartBarrieredMutex(registry, start_barrier),
        entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
            trade_cycle_id_factory=lambda: "tc-id",
            execution_port=execution_port,
        ),
    )

    results: list[StrategyInstanceRuntimeState] = []
    results_lock = threading.Lock()

    def _run() -> None:
        r = orch.process(unit)
        with results_lock:
            results.append(r)

    t1 = threading.Thread(target=_run, name="t1")
    t2 = threading.Thread(target=_run, name="t2")
    t1.start()
    t2.start()

    assert gate.first_entered.wait(timeout=_TIMEOUT), "winner never reached the gate"
    winner_name = gate.first_thread_name
    assert winner_name is not None
    loser_name = "t2" if winner_name == "t1" else "t1"

    # Deterministic, not timing-based: the loser is either physically blocked
    # on the real per-key lock (correct) or it is not (broken) — there is no
    # race window because the OS lock, not a clock, gates this snapshot.
    loser_events_before_release = sum(1 for e in log.snapshot() if e.endswith(f":{loser_name}"))

    gate.release()
    t1.join(timeout=_TIMEOUT)
    t2.join(timeout=_TIMEOUT)

    return _SameInstancePairResult(
        winner_name=winner_name,
        loser_name=loser_name,
        loser_events_before_release=loser_events_before_release,
        events=log.snapshot(),
        resolver_received_states=resolver.received_states,
        save_results=repo.save_results,
        process_results=results,
    )


# ---------------------------------------------------------------------------
# 5.1: Same-instance invocations serialize with non-overlapping critical
# sections.
# ---------------------------------------------------------------------------


class TestSameInstanceSerialization:
    def test_loser_does_not_load_state_before_winner_releases(self) -> None:
        result = _run_same_instance_pair()

        assert result.loser_events_before_release == 0

    def test_critical_sections_do_not_overlap(self) -> None:
        result = _run_same_instance_pair()

        assert len(result.process_results) == 2
        winner_indices = [
            i for i, e in enumerate(result.events) if e.endswith(f":{result.winner_name}")
        ]
        loser_indices = [
            i for i, e in enumerate(result.events) if e.endswith(f":{result.loser_name}")
        ]
        # Winner applies the desired entry (get_or_create, resolve, route,
        # reconcile, save). The loser observes that already-applied entry via
        # the fresh post-save state (5.2) and reconciles to an idempotent
        # NoOp, so it never reaches the execution port or save.
        assert len(winner_indices) == 5
        assert len(loser_indices) == 3
        assert max(winner_indices) < min(loser_indices)


# ---------------------------------------------------------------------------
# 5.2: A waiting same-instance invocation observes the state saved by the
# preceding invocation.
# ---------------------------------------------------------------------------


class TestSameInstanceFreshStateAfterWait:
    def test_waiting_invocation_resolves_state_saved_by_first(self) -> None:
        result = _run_same_instance_pair()

        assert len(result.resolver_received_states) == 2
        winner_received, loser_received = result.resolver_received_states
        assert len(result.save_results) == 1
        saved_by_winner = result.save_results[0]

        assert winner_received.current_trade_cycle is None
        assert loser_received == saved_by_winner
        assert loser_received.current_trade_cycle is not None


# ---------------------------------------------------------------------------
# 5.3: Different strategy-instance IDs progress inside their critical
# sections at the same time.
# ---------------------------------------------------------------------------


class _NoOpRouter:
    def route(self, item: PositionResolvedStrategyInstance) -> LiveEntryProjectedStrategyInstance:
        return LiveEntryProjectedStrategyInstance(item, None)


class _UnusedExecutionPort:
    def execute(self, command: Any, source_state: Any) -> Any:
        raise AssertionError("execution port must not run for a NoOp decision")


class _RendezvousResolver:
    """Resolver that only returns once both threads are simultaneously inside it."""

    def __init__(self, inside_barrier: threading.Barrier) -> None:
        self._inside_barrier = inside_barrier

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        self._inside_barrier.wait(timeout=_TIMEOUT)
        return _resolved(state)


class TestDifferentInstanceOverlap:
    def test_different_instance_ids_overlap_inside_critical_sections(self) -> None:
        registry = StrategyInstanceKeyedMutexRegistry()
        start_barrier = threading.Barrier(2, timeout=_TIMEOUT)
        inside_barrier = threading.Barrier(2, timeout=_TIMEOUT)

        def _build(sid: str) -> tuple[StrategyRuntimeOrchestrator, Any]:
            unit = _make_unit(sid)
            repo = InMemoryStrategyInstanceRuntimeStateRepository()
            repo.get_or_create(_request_for(sid))
            orch = StrategyRuntimeOrchestrator(
                state_repository=repo,
                open_position_resolver=_RendezvousResolver(inside_barrier),
                use_case_router=_NoOpRouter(),
                keyed_mutex_registry=_StartBarrieredMutex(registry, start_barrier),
                entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                    trade_cycle_id_factory=lambda: "tc-id",
                    execution_port=_UnusedExecutionPort(),
                ),
            )
            return orch, unit

        orch_a, unit_a = _build(_SID_A)
        orch_b, unit_b = _build(_SID_B)

        results: list[Any] = []
        results_lock = threading.Lock()

        def _run(orch: StrategyRuntimeOrchestrator, unit: Any) -> None:
            try:
                r: Any = orch.process(unit)
            except Exception as exc:  # noqa: BLE001 - captured for cross-thread assertion
                r = exc
            with results_lock:
                results.append(r)

        t1 = threading.Thread(target=_run, args=(orch_a, unit_a))
        t2 = threading.Thread(target=_run, args=(orch_b, unit_b))
        t1.start()
        t2.start()
        t1.join(timeout=_TIMEOUT)
        t2.join(timeout=_TIMEOUT)

        # If the registry wrongly serialized distinct keys, one thread would
        # still be blocked acquiring the (wrongly shared) lock and could never
        # reach `inside_barrier`; the other would time out waiting on it and
        # `process(...)` would raise `threading.BrokenBarrierError` instead of
        # returning a state.
        assert len(results) == 2
        assert all(isinstance(r, StrategyInstanceRuntimeState) for r in results), results
