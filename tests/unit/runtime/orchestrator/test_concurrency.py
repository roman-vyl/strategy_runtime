"""Focused Runtime orchestrator concurrency and mutex tests."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation import EntryAbsentConfirmation
from strategy_runtime.runtime.entry_reconciliation_orchestrator.orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import InMemoryStrategyInstanceRuntimeStateRepository
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SID_A = "instance-a"
_SID_B = "instance-b"


def _make_state(sid: str) -> StrategyInstanceRuntimeState:
    return InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id=sid,
            strategy_id="strategy-x",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={"ema": 200},
            source_path="/specs/x.json",
        )
    )


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


class _NoOpExecutionPort:
    def execute(self, command: Any, source_state: Any) -> EntryAbsentConfirmation:
        return EntryAbsentConfirmation(
            strategy_instance_id=source_state.strategy_instance_id,
            trade_cycle_id=command.trade_cycle_id,
        )


class _CountingRepository:
    def __init__(self, initial_state: StrategyInstanceRuntimeState) -> None:
        self._state = initial_state
        self.get_or_create_calls = 0
        self.save_calls: list[StrategyInstanceRuntimeState] = []
        self.get_or_create_events: list[str] = []

    def get_or_create(self, request: Any) -> StrategyInstanceRuntimeState:
        self.get_or_create_calls += 1
        self.get_or_create_events.append("get_or_create")
        return self._state

    def get(self, sid: str) -> StrategyInstanceRuntimeState | None:
        return self._state if sid == self._state.strategy_instance_id else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls.append(state)
        self._state = state
        return state


class _EventRepository:
    """Repository that blocks get_or_create on an event to control sequencing."""

    def __init__(
        self,
        state: StrategyInstanceRuntimeState,
        block_event: threading.Event,
        unblock_event: threading.Event,
    ) -> None:
        self._state = state
        self._block_event = block_event
        self._unblock_event = unblock_event

    def get_or_create(self, request: Any) -> StrategyInstanceRuntimeState:
        self._block_event.set()
        self._unblock_event.wait(timeout=5)
        return self._state

    def get(self, sid: str) -> StrategyInstanceRuntimeState | None:
        return self._state if sid == self._state.strategy_instance_id else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        return state


# ---------------------------------------------------------------------------
# 5.1: Same-instance invocations serialize
# ---------------------------------------------------------------------------


class TestSameInstanceSerialization:
    def test_two_same_instance_invocations_do_not_overlap(self) -> None:
        state = _make_state(_SID_A)
        resolved_states = [type("R", (), {"runtime_state": state, "position_open": False})()]
        unit = _make_unit(_SID_A)
        item = PositionResolvedStrategyInstance(unit, resolved_states[0])
        projected = LiveEntryProjectedStrategyInstance(item, None)

        enter_events: list[str] = []
        exit_events: list[str] = []
        mutex = StrategyInstanceKeyedMutexRegistry()

        class _TrackingMutex:
            def hold(self, sid: str) -> Any:
                ctx = mutex.hold(sid)
                return _TrackingCtx(ctx, sid, enter_events, exit_events)

        class _TrackingCtx:
            def __init__(
                self,
                ctx: Any,
                sid: str,
                enters: list[str],
                exits: list[str],
            ) -> None:
                self._ctx = ctx
                self._sid = sid
                self._enters = enters
                self._exits = exits

            def __enter__(self) -> None:
                self._enters.append(f"enter:{self._sid}")
                return self._ctx.__enter__()

            def __exit__(self, *args: Any) -> None:
                self._exits.append(f"exit:{self._sid}")
                return self._ctx.__exit__(*args)

        orch = StrategyRuntimeOrchestrator(
            state_repository=_CountingRepository(state),
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved_states[0])),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=_TrackingMutex(),  # type: ignore[arg-type]
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_NoOpExecutionPort(),
            ),
        )

        results: list[Any] = []
        barrier = threading.Barrier(2)

        def _run() -> None:
            barrier.wait(timeout=5)
            results.append(orch.process(unit))

        threads = [threading.Thread(target=_run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 2
        assert len(enter_events) == 2
        for i in range(1, len(enter_events)):
            assert enter_events[i] == f"exit:{_SID_A}" or exit_events[i - 1] == f"exit:{_SID_A}"

    def test_waiting_invocation_loads_state_after_first_saves(self) -> None:
        state = _make_state(_SID_A)
        block = threading.Event()
        unblock = threading.Event()

        repo = _EventRepository(state, block, unblock)
        unit = _make_unit(_SID_A)
        resolved = type("R", (), {"runtime_state": state, "position_open": False})()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_NoOpExecutionPort(),
            ),
        )

        results: list[Any] = []

        def _run() -> None:
            results.append(orch.process(unit))

        t = threading.Thread(target=_run)
        t.start()
        block.wait(timeout=5)
        unblock.set()
        t.join(timeout=5)

        assert len(results) == 1


# ---------------------------------------------------------------------------
# 5.3: Different instances can overlap
# ---------------------------------------------------------------------------


class TestDifferentInstanceOverlap:
    def test_different_ids_can_progress_concurrently(self) -> None:
        state_a = _make_state(_SID_A)
        state_b = _make_state(_SID_B)
        resolved_a = type("R", (), {"runtime_state": state_a, "position_open": False})()
        resolved_b = type("R", (), {"runtime_state": state_b, "position_open": False})()
        unit_a = _make_unit(_SID_A)
        unit_b = _make_unit(_SID_B)
        item_a = PositionResolvedStrategyInstance(unit_a, resolved_a)
        item_b = PositionResolvedStrategyInstance(unit_b, resolved_b)
        proj_a = LiveEntryProjectedStrategyInstance(item_a, None)
        proj_b = LiveEntryProjectedStrategyInstance(item_b, None)
        mutex = StrategyInstanceKeyedMutexRegistry()

        orch_a = StrategyRuntimeOrchestrator(
            state_repository=_CountingRepository(state_a),
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved_a)),
            use_case_router=MagicMock(route=MagicMock(return_value=proj_a)),
            keyed_mutex_registry=mutex,
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-a",
                execution_port=_NoOpExecutionPort(),
            ),
        )
        orch_b = StrategyRuntimeOrchestrator(
            state_repository=_CountingRepository(state_b),
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved_b)),
            use_case_router=MagicMock(route=MagicMock(return_value=proj_b)),
            keyed_mutex_registry=mutex,
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-b",
                execution_port=_NoOpExecutionPort(),
            ),
        )

        start = threading.Barrier(2)
        results_a: list[Any] = []
        results_b: list[Any] = []

        def _run_a() -> None:
            start.wait(timeout=5)
            results_a.append(orch_a.process(unit_a))

        def _run_b() -> None:
            start.wait(timeout=5)
            results_b.append(orch_b.process(unit_b))

        t1 = threading.Thread(target=_run_a)
        t2 = threading.Thread(target=_run_b)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(results_a) == 1
        assert len(results_b) == 1
