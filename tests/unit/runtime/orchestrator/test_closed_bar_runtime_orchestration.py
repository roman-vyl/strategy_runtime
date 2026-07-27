"""Focused Runtime orchestrator sequencing, persistence, branch, and error tests."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation import (
    EntryAppliedConfirmation,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator.orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupResponse,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.resolver import OpenPositionResolver
from strategy_runtime.runtime.orchestrator.errors import (
    OpenTradeProjectionUnsupportedError,
    UnknownStrategyProjectionError,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.committed_bar.orchestrator import CommittedBarOrchestrator
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SID = "ema_pullback:abc"
_SID_DIFFERENT = "ema_pullback:def"


def _state_request(
    sid: str = _SID,
    strategy_id: str = "ema_pullback",
) -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=sid,
        strategy_id=strategy_id,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )


def _runtime_state(sid: str = _SID) -> StrategyInstanceRuntimeState:
    return InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(_state_request(sid))


def _processing_unit(sid: str = _SID) -> StrategyBarProcessingUnit[DeploymentSpecification]:
    deployment = DeploymentSpecification(
        strategy_instance_id=sid,
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="ema_pullback",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )
    return StrategyBarProcessingUnit(
        strategy_instance_id=sid,
        deployment=deployment,
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 1000),
    )


def _desired_entry(side: str = "long") -> DesiredEntry:
    return DesiredEntry(side, 900, "100.00", "99.00", "103.00", "runner")


class _Abi:
    def __init__(self, response: OpenPositionLookupResponse | None = None) -> None:
        self.response = response

    def lookup(self, request: object) -> OpenPositionLookupResponse:
        assert self.response is not None
        return self.response


def _resolved_state(
    *,
    position_open: bool,
    state: StrategyInstanceRuntimeState | None = None,
) -> PositionResolvedStrategyInstanceRuntimeState:
    target = state or _runtime_state()
    response = (
        OpenPositionLookupResponse(True, 950, "100.5")
        if position_open
        else OpenPositionLookupResponse(False)
    )
    return OpenPositionResolver(_Abi(response)).resolve(target)


def _live_projection(
    *,
    sid: str = _SID,
    desired: DesiredEntry | None = None,
) -> LiveEntryProjectedStrategyInstance:
    if desired is None:
        desired = _desired_entry()
    state = _runtime_state(sid)
    resolved = _resolved_state(position_open=False, state=state)
    unit = _processing_unit(sid)
    return LiveEntryProjectedStrategyInstance(
        PositionResolvedStrategyInstance(unit, resolved), desired
    )


def _open_projection() -> OpenTradeProjectedStrategyInstance:
    state = _runtime_state()
    return replace(
        state,
        current_trade_cycle=CurrentTradeCycle(
            "cycle-1",
            AppliedEntryPackage(
                applied_desired_entry=_desired_entry(),
                calculated_quantity="0.1",
            ),
        ),
    )
    # unreachable; kept for readability


class _FakeExecutionPort:
    """Entry reconciliation execution port that returns a valid confirmation."""

    def __init__(self, calculated_quantity: str = "0.1") -> None:
        self.calculated_quantity = calculated_quantity
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
        self.calls.append((command, source_state))
        return EntryAppliedConfirmation(
            strategy_instance_id=source_state.strategy_instance_id,
            trade_cycle_id=command.trade_cycle_id,
            applied_desired_entry=command.desired_entry,
            calculated_quantity=self.calculated_quantity,
        )


class _RecordingMutexRegistry:
    """Mutex registry that records event order around hold contexts."""

    def __init__(self, real: StrategyInstanceKeyedMutexRegistry) -> None:
        self._real = real
        self.events: list[str] = []

    def hold(self, strategy_instance_id: str) -> Any:
        self.events.append(f"hold_acquired:{strategy_instance_id}")
        ctx = self._real.hold(strategy_instance_id)
        return _RecordingContext(ctx, self.events)


class _RecordingContext:
    def __init__(self, ctx: Any, events: list[str]) -> None:
        self._ctx = ctx
        self._events = events

    def __enter__(self) -> None:
        return self._ctx.__enter__()

    def __exit__(self, *args: Any) -> None:
        self._events.append("hold_released")
        return self._ctx.__exit__(*args)


class _FakeRepository:
    """Repository that records get_or_create and save calls."""

    def __init__(self, state: StrategyInstanceRuntimeState) -> None:
        self._state = state
        self.get_or_create_calls: list[str] = []
        self.save_calls: list[StrategyInstanceRuntimeState] = []

    def get_or_create(self, request: Any) -> StrategyInstanceRuntimeState:
        self.get_or_create_calls.append("get_or_create")
        return self._state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._state if strategy_instance_id == self._state.strategy_instance_id else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls.append(state)
        self._state = state
        return state


class _FakeRepositoryDistinctReturn:
    """Repository whose save returns a distinct object from input."""

    def __init__(self, state: StrategyInstanceRuntimeState) -> None:
        self._state = state
        self.save_calls: list[StrategyInstanceRuntimeState] = []

    def get_or_create(self, request: Any) -> StrategyInstanceRuntimeState:
        return self._state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._state if strategy_instance_id == self._state.strategy_instance_id else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls.append(state)
        saved = replace(state, risk_multiplier="2")
        self._state = saved
        return saved


class _FailingRepository:
    """Repository that raises on save."""

    def __init__(
        self,
        state: StrategyInstanceRuntimeState,
        *,
        save_error: Exception | None = None,
        get_or_create_error: Exception | None = None,
    ) -> None:
        self._state = state
        self.save_calls: list[StrategyInstanceRuntimeState] = []
        self.save_error = save_error
        self.get_or_create_error = get_or_create_error

    def get_or_create(self, request: Any) -> StrategyInstanceRuntimeState:
        if self.get_or_create_error is not None:
            raise self.get_or_create_error
        return self._state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._state if strategy_instance_id == self._state.strategy_instance_id else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls.append(state)
        if self.save_error is not None:
            raise self.save_error
        return state


class _FailingResolver:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def resolve(self, state: Any) -> Any:
        raise self._error


class _FailingRouter:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def route(self, item: Any) -> Any:
        raise self._error


def _make_orchestrator(
    *,
    repository: Any = None,
    execution_port: Any = None,
    mutex_registry: Any = None,
) -> tuple[StrategyRuntimeOrchestrator, Any, Any, Any]:
    state = _runtime_state()
    repo = repository or _FakeRepository(state)
    resolved = _resolved_state(position_open=False, state=state)
    unit = _processing_unit()
    item = PositionResolvedStrategyInstance(unit, resolved)
    projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())
    ep = execution_port or _FakeExecutionPort()
    entry_orch = EntryReconciliationOrchestrator(
        trade_cycle_id_factory=lambda: "tc-factory-id",
        execution_port=ep,
    )
    r = StrategyInstanceKeyedMutexRegistry()
    mutex = mutex_registry or r
    orch = StrategyRuntimeOrchestrator(
        state_repository=repo,
        open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
        use_case_router=MagicMock(route=MagicMock(return_value=projected)),
        keyed_mutex_registry=mutex,
        entry_reconciliation_orchestrator=entry_orch,
    )
    return orch, repo, ep, projected


# ---------------------------------------------------------------------------
# 4. Sequencing and Persistence Tests
# ---------------------------------------------------------------------------


class TestSequencingAndPersistence:
    def test_mutex_acquired_before_state_load(self) -> None:
        events: list[str] = []
        real = StrategyInstanceKeyedMutexRegistry()

        class _EventMutex:
            def hold(self, sid: str) -> _EventContext:
                events.append("hold_acquired")
                return _EventContext(real.hold(sid), events)

        class _EventContext:
            def __init__(self, ctx: Any, evts: list[str]) -> None:
                self._ctx = ctx
                self._events = evts

            def __enter__(self) -> None:
                return self._ctx.__enter__()

            def __exit__(self, *args: Any) -> None:
                self._events.append("hold_released")
                return self._ctx.__exit__(*args)

        state = _runtime_state()
        repo = _FakeRepository(state)
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=_EventMutex(),  # type: ignore[arg-type]
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        orch.process(unit)
        assert events[0] == "hold_acquired"

    def test_mutex_held_through_all_stages(self) -> None:
        call_order: list[str] = []
        state = _runtime_state()
        real_mutex = StrategyInstanceKeyedMutexRegistry()

        class _OrderMutex:
            def hold(self, sid: str) -> Any:
                call_order.append("mutex:acquire")
                return real_mutex.hold(sid)

        ep = _FakeExecutionPort()
        original_execute = ep.execute

        def _tracked_execute(command: Any, source_state: Any) -> Any:
            call_order.append("reconciliation:execute")
            return original_execute(command, source_state)

        ep.execute = _tracked_execute  # type: ignore[method-assign]

        unit = _processing_unit()
        resolved = _resolved_state(position_open=False, state=state)
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        repo = _FakeRepository(state)

        def _tracked_resolve(s: Any) -> Any:
            call_order.append("resolver:resolve")
            return resolved

        def _tracked_route(i: Any) -> Any:
            call_order.append("router:route")
            return projected

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(side_effect=_tracked_resolve)),
            use_case_router=MagicMock(route=MagicMock(side_effect=_tracked_route)),
            keyed_mutex_registry=_OrderMutex(),  # type: ignore[arg-type]
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=ep,
            ),
        )

        orch.process(unit)
        assert call_order == [
            "mutex:acquire",
            "resolver:resolve",
            "router:route",
            "reconciliation:execute",
        ]

    def test_live_entry_invokes_nested_orchestrator_exactly_once_with_exact_projection(
        self,
    ) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        ep = _FakeExecutionPort()
        entry_orch = EntryReconciliationOrchestrator(
            trade_cycle_id_factory=lambda: "tc-id",
            execution_port=ep,
        )
        original_execute = entry_orch.execute
        call_args: list[Any] = []

        def _tracked_execute(proj: Any) -> Any:
            call_args.append(proj)
            return original_execute(proj)

        entry_orch.execute = _tracked_execute  # type: ignore[method-assign]

        repo = _FakeRepository(state)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=entry_orch,
        )

        result = orch.process(unit)

        assert len(call_args) == 1
        assert call_args[0] is projected
        assert isinstance(result, StrategyInstanceRuntimeState)
        assert result.strategy_instance_id == state.strategy_instance_id

    def test_noop_returns_source_aggregate_with_zero_saves(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)

        repo = _FakeRepository(state)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        result = orch.process(unit)
        assert result == state
        assert repo.save_calls == []

    def test_value_equal_different_object_yields_zero_saves(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)

        different_but_equal = replace(state)

        repo = _FakeRepository(state)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=MagicMock(
                execute=MagicMock(return_value=different_but_equal)
            ),
        )

        result = orch.process(unit)
        assert result == state
        assert result is not state
        assert repo.save_calls == []

    def test_value_different_result_saved_exactly_once(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        class _ApplyExecutionPort:
            def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
                return EntryAppliedConfirmation(
                    strategy_instance_id=source_state.strategy_instance_id,
                    trade_cycle_id=command.trade_cycle_id,
                    applied_desired_entry=command.desired_entry,
                    calculated_quantity="0.5",
                )

        repo = _FakeRepository(state)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_ApplyExecutionPort(),
            ),
        )

        result = orch.process(unit)
        assert result != state
        assert result.current_trade_cycle is not None
        assert len(repo.save_calls) == 1
        assert repo.save_calls[0] == result

    def test_value_equal_result_as_different_object_yields_zero_saves(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        different_but_equal = replace(state)

        repo = _FakeRepository(state)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=MagicMock(
                execute=MagicMock(return_value=different_but_equal)
            ),
        )

        result = orch.process(unit)
        assert result == state
        assert result is not state
        assert repo.save_calls == []

    def test_process_returns_exact_save_result(self) -> None:
        state = _runtime_state()
        saved_return = replace(state, risk_multiplier="3")
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        class _ApplyExecutionPort:
            def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
                return EntryAppliedConfirmation(
                    strategy_instance_id=source_state.strategy_instance_id,
                    trade_cycle_id=command.trade_cycle_id,
                    applied_desired_entry=command.desired_entry,
                    calculated_quantity="0.5",
                )

        repo = _FakeRepositoryDistinctReturn(state)
        repo.save = MagicMock(return_value=saved_return)  # type: ignore[method-assign]

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_ApplyExecutionPort(),
            ),
        )

        result = orch.process(unit)
        assert result is saved_return

    def test_no_reload_for_reconciliation(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        repo = _FakeRepository(state)
        original_get_or_create = repo.get_or_create

        def _tracked_get_or_create(request: Any) -> StrategyInstanceRuntimeState:
            return original_get_or_create(request)

        repo.get_or_create = _tracked_get_or_create  # type: ignore[method-assign]

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        orch.process(unit)
        assert len(repo.get_or_create_calls) == 1


# ---------------------------------------------------------------------------
# 5. Concurrency and Release Tests
# ---------------------------------------------------------------------------


class TestConcurrencyAndRelease:
    def test_same_instance_no_overlap(self) -> None:
        events: list[str] = []
        state = _runtime_state()
        real_mutex = StrategyInstanceKeyedMutexRegistry()
        barrier = threading.Barrier(2)

        class _OrderingMutex:
            def hold(self, sid: str) -> Any:
                ctx = real_mutex.hold(sid)
                return _BarrierContext(ctx, events, sid, barrier)

        class _BarrierContext:
            def __init__(
                self, ctx: Any, events: list[str], sid: str, barrier: threading.Barrier
            ) -> None:
                self._ctx = ctx
                self._events = events
                self._sid = sid
                self._barrier = barrier

            def __enter__(self) -> None:
                self._events.append(f"acquired:{self._sid}")
                self._barrier.wait(timeout=5)
                return self._ctx.__enter__()

            def __exit__(self, *args: Any) -> None:
                self._events.append(f"released:{self._sid}")
                return self._ctx.__exit__(*args)

        unit = _processing_unit()
        resolved = _resolved_state(position_open=False, state=state)
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=_OrderingMutex(),  # type: ignore[arg-type]
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        results: list[tuple[str, Any]] = []

        def _run(label: str) -> None:
            try:
                r = orch.process(unit)
                results.append((label, r))
            except Exception as e:
                results.append((label, e))

        t1 = threading.Thread(target=_run, args=("first",))
        t2 = threading.Thread(target=_run, args=("second",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(results) == 2
        acquired_indices = [i for i, e in enumerate(events) if e.startswith("acquired:")]
        released_indices = [i for i, e in enumerate(events) if e.startswith("released:")]
        for idx in acquired_indices:
            assert released_indices[0] < idx or released_indices[-1] > idx

    def test_different_instances_can_progress_concurrently(self) -> None:
        state_a = _runtime_state(_SID)
        state_b = _runtime_state(_SID_DIFFERENT)
        resolved_a = _resolved_state(position_open=False, state=state_a)
        resolved_b = _resolved_state(position_open=False, state=state_b)
        unit_a = _processing_unit(_SID)
        unit_b = _processing_unit(_SID_DIFFERENT)
        item_a = PositionResolvedStrategyInstance(unit_a, resolved_a)
        item_b = PositionResolvedStrategyInstance(unit_b, resolved_b)
        proj_a = LiveEntryProjectedStrategyInstance(item_a, None)
        proj_b = LiveEntryProjectedStrategyInstance(item_b, None)
        repo_a = _FakeRepository(state_a)
        repo_b = _FakeRepository(state_b)

        orch_a = StrategyRuntimeOrchestrator(
            state_repository=repo_a,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved_a)),
            use_case_router=MagicMock(route=MagicMock(return_value=proj_a)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-a",
                execution_port=_FakeExecutionPort(),
            ),
        )
        orch_b = StrategyRuntimeOrchestrator(
            state_repository=repo_b,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved_b)),
            use_case_router=MagicMock(route=MagicMock(return_value=proj_b)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-b",
                execution_port=_FakeExecutionPort(),
            ),
        )

        barrier = threading.Barrier(2)
        results_a: list[Any] = []
        results_b: list[Any] = []

        def _run_a() -> None:
            barrier.wait(timeout=5)
            results_a.append(orch_a.process(unit_a))

        def _run_b() -> None:
            barrier.wait(timeout=5)
            results_b.append(orch_b.process(unit_b))

        t1 = threading.Thread(target=_run_a)
        t2 = threading.Thread(target=_run_b)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(results_a) == 1
        assert len(results_b) == 1

    def test_mutex_released_after_noop_success(self) -> None:
        state = _runtime_state()
        real = StrategyInstanceKeyedMutexRegistry()
        unit = _processing_unit()
        resolved = _resolved_state(position_open=False, state=state)
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=real,
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        orch.process(unit)
        with real.hold(_SID):
            pass

    def test_mutex_released_after_saved_replacement_success(self) -> None:
        state = _runtime_state()
        real = StrategyInstanceKeyedMutexRegistry()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        class _ApplyExecutionPort:
            def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
                return EntryAppliedConfirmation(
                    strategy_instance_id=source_state.strategy_instance_id,
                    trade_cycle_id=command.trade_cycle_id,
                    applied_desired_entry=command.desired_entry,
                    calculated_quantity="0.5",
                )

        repo = _FakeRepository(state)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=real,
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_ApplyExecutionPort(),
            ),
        )

        orch.process(unit)
        with real.hold(_SID):
            pass

    @pytest.mark.parametrize(
        ("error_factory", "error_label"),
        [
            (lambda: RuntimeError("get_or_create failed"), "get_or_create"),
            (lambda: RuntimeError("resolver failed"), "resolver"),
            (lambda: RuntimeError("router failed"), "router"),
            (lambda: RuntimeError("reconciliation failed"), "reconciliation"),
            (lambda: RuntimeError("save failed"), "save"),
            (lambda: OpenTradeProjectionUnsupportedError(), "open_trade"),
            (lambda: UnknownStrategyProjectionError(), "unknown"),
        ],
    )
    def test_mutex_released_after_each_exception(
        self, error_factory: Any, error_label: str
    ) -> None:
        error = error_factory()
        state = _runtime_state()
        real = StrategyInstanceKeyedMutexRegistry()
        unit = _processing_unit()
        resolved = _resolved_state(position_open=False, state=state)
        item = PositionResolvedStrategyInstance(unit, resolved)

        if error_label == "open_trade":
            projection: Any = OpenTradeProjectedStrategyInstance(
                item, DesiredProtection("99.5", None)
            )
        elif error_label == "unknown":
            projection = "not-a-valid-projection"
        else:
            projection = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        if error_label == "get_or_create":
            repo: Any = _FailingRepository(state, get_or_create_error=error)
        elif error_label == "save":
            repo = _FailingRepository(state, save_error=error)
        else:
            repo = _FakeRepository(state)

        if error_label == "resolver":
            resolver: Any = _FailingResolver(error)
        else:
            resolver = MagicMock(resolve=MagicMock(return_value=resolved))

        if error_label == "router":
            use_case_router: Any = _FailingRouter(error)
        else:
            use_case_router = MagicMock(route=MagicMock(return_value=projection))

        if error_label == "reconciliation":
            ep: Any = MagicMock(execute=MagicMock(side_effect=error))
        elif error_label == "open_trade" or error_label == "unknown":
            ep = _FakeExecutionPort()
        else:
            ep = _FakeExecutionPort()

        entry_orch = EntryReconciliationOrchestrator(
            trade_cycle_id_factory=lambda: "tc-id",
            execution_port=ep,
        )

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=resolver,
            use_case_router=use_case_router,
            keyed_mutex_registry=real,
            entry_reconciliation_orchestrator=entry_orch,
        )

        with pytest.raises(type(error)):
            orch.process(unit)

        with real.hold(_SID):
            pass


# ---------------------------------------------------------------------------
# 6. Typed Branch and Error-Boundary Tests
# ---------------------------------------------------------------------------


class TestTypedBranchAndErrorBoundary:
    def test_open_trade_raises_without_reconciliation_or_save(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(
            position_open=True,
            state=replace(
                state,
                current_trade_cycle=CurrentTradeCycle(
                    "cycle-1",
                    AppliedEntryPackage(
                        applied_desired_entry=_desired_entry(),
                        calculated_quantity="0.1",
                    ),
                ),
            ),
        )
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projection = OpenTradeProjectedStrategyInstance(item, DesiredProtection("99.5", None))
        repo = _FakeRepository(state)
        ep = _FakeExecutionPort()
        entry_orch = EntryReconciliationOrchestrator(
            trade_cycle_id_factory=lambda: "tc-id",
            execution_port=ep,
        )

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projection)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=entry_orch,
        )

        with pytest.raises(OpenTradeProjectionUnsupportedError):
            orch.process(unit)
        assert ep.calls == []
        assert repo.save_calls == []

    def test_open_trade_cannot_produce_successful_dispatch(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(
            position_open=True,
            state=replace(
                state,
                current_trade_cycle=CurrentTradeCycle(
                    "cycle-1",
                    AppliedEntryPackage(
                        applied_desired_entry=_desired_entry(),
                        calculated_quantity="0.1",
                    ),
                ),
            ),
        )
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projection = OpenTradeProjectedStrategyInstance(item, DesiredProtection("99.5", None))
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projection)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        with pytest.raises(OpenTradeProjectionUnsupportedError):
            orch.dispatch(unit)

    def test_unknown_projection_raises_without_reconciliation_or_save(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        repo = _FakeRepository(state)
        ep = _FakeExecutionPort()

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value="unknown-type")),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=ep,
            ),
        )

        with pytest.raises(UnknownStrategyProjectionError):
            orch.process(unit)
        assert ep.calls == []
        assert repo.save_calls == []

    def test_get_or_create_error_propagates_without_save(self) -> None:
        state = _runtime_state()
        error = RuntimeError("db down")
        repo = _FailingRepository(state, get_or_create_error=error)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(),
            use_case_router=MagicMock(),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        with pytest.raises(RuntimeError, match="db down"):
            orch.process(_processing_unit())
        assert repo.save_calls == []

    def test_resolver_error_propagates_without_save(self) -> None:
        state = _runtime_state()
        error = RuntimeError("resolver broken")
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=_FailingResolver(error),
            use_case_router=MagicMock(),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        with pytest.raises(RuntimeError, match="resolver broken"):
            orch.process(_processing_unit())
        assert repo.save_calls == []

    def test_router_engine_error_propagates_without_save(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        error = RuntimeError("engine timeout")
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=_FailingRouter(error),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        with pytest.raises(RuntimeError, match="engine timeout"):
            orch.process(_processing_unit())
        assert repo.save_calls == []

    def test_reconciliation_error_propagates_without_save(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())
        error = RuntimeError("reconciliation broken")
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=MagicMock(execute=MagicMock(side_effect=error)),
        )

        with pytest.raises(RuntimeError, match="reconciliation broken"):
            orch.process(unit)
        assert repo.save_calls == []

    def test_save_error_propagates_after_exactly_one_attempt(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())
        save_error = RuntimeError("save failed")
        repo = _FailingRepository(state, save_error=save_error)

        class _ApplyExecutionPort:
            def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
                return EntryAppliedConfirmation(
                    strategy_instance_id=source_state.strategy_instance_id,
                    trade_cycle_id=command.trade_cycle_id,
                    applied_desired_entry=command.desired_entry,
                    calculated_quantity="0.5",
                )

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_ApplyExecutionPort(),
            ),
        )

        with pytest.raises(RuntimeError, match="save failed"):
            orch.process(unit)
        assert len(repo.save_calls) == 1

    def test_dispatch_returns_success_only_after_process_succeeds(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        result = orch.dispatch(unit)
        assert isinstance(result, StrategyCycleDispatchOutcome)
        assert result.strategy_instance_id == _SID
        assert result.status.value == "succeeded"

    def test_dispatch_propagates_exact_exception_on_failure(self) -> None:
        state = _runtime_state()
        error = RuntimeError("boom")
        repo = _FailingRepository(state, get_or_create_error=error)
        unit = _processing_unit()

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(),
            use_case_router=MagicMock(),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        with pytest.raises(RuntimeError, match="boom") as exc_info:
            orch.dispatch(unit)
        assert exc_info.value is error

    def test_committed_bar_orchestrator_creates_dispatch_failed(self) -> None:
        error = RuntimeError("semantic boom")

        class _FailingDispatcher:
            def dispatch(self, unit: Any) -> Any:
                raise error

        committed_orch = CommittedBarOrchestrator(
            deployment_catalog=MagicMock(load_snapshot=MagicMock(return_value="snap")),
            deployment_selector=MagicMock(
                select=MagicMock(
                    return_value=(
                        __import__(
                            "strategy_runtime.utility.committed_bar.models",
                            fromlist=["SelectedDeployment"],
                        ).SelectedDeployment(
                            _SID,
                            DeploymentSpecification(
                                strategy_instance_id=_SID,
                                enabled=True,
                                instrument="BTCUSDT.P",
                                base_timeframe="5m",
                                strategy_id="ema_pullback",
                                raw_spec={"ema": 200},
                                source_path="/specs/a.json",
                            ),
                        ),
                    ),
                ),
            ),
            strategy_cycle_dispatcher=_FailingDispatcher(),
            processing_journal=MagicMock(),
        )

        result = committed_orch.process(CommittedBarEvent("BTCUSDT.P", "5m", 1000))

        assert result.failed_count == 1
        assert result.outcomes[0].error_code == "strategy_cycle_dispatch_failed"


# ---------------------------------------------------------------------------
# 8.1: Integration-style orchestration tests
# ---------------------------------------------------------------------------


class TestProcessReturnsFinalState:
    def test_process_returns_state_not_projection(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        result = orch.process(unit)
        assert isinstance(result, StrategyInstanceRuntimeState)
        assert not isinstance(result, LiveEntryProjectedStrategyInstance)
        assert not isinstance(result, OpenTradeProjectedStrategyInstance)

    def test_dispatch_returns_outcome_not_state(self) -> None:
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)
        repo = _FakeRepository(state)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        result = orch.dispatch(unit)
        assert isinstance(result, StrategyCycleDispatchOutcome)
        assert not isinstance(result, StrategyInstanceRuntimeState)
