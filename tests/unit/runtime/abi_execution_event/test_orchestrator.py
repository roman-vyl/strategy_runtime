"""Focused sequencing, persistence, and error-boundary tests for
AbiExecutionEventOrchestrator."""

from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest

from strategy_runtime.runtime.abi_execution_event.models import AbiFirstFillExecutionEvent
from strategy_runtime.runtime.abi_execution_event.orchestrator import (
    AbiExecutionEventOrchestrator,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.errors import StrategyInstanceStateNotFound
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SID = "instance-a"
_TRADE_CYCLE_ID = "cycle-1"
_SOURCE_PLAN_BAR_OPEN_TIME_MS = 900_000
_FIRST_FILL_AT_MS = 905_000


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", _SOURCE_PLAN_BAR_OPEN_TIME_MS, "100", "99", "103", "runner")


def _runtime_state(
    *,
    sid: str = _SID,
    base_timeframe: str = "15m",
    trade_cycle_id: str | None = _TRADE_CYCLE_ID,
    frozen_entry_context: FrozenExecutedEntryContext | None = None,
) -> StrategyInstanceRuntimeState:
    current_trade_cycle = None
    if trade_cycle_id is not None:
        current_trade_cycle = CurrentTradeCycle(
            trade_cycle_id,
            AppliedEntryPackage(_desired_entry(), "0.01"),
            frozen_entry_context,
        )
    return StrategyInstanceRuntimeState(
        strategy_instance_id=sid,
        strategy_id="strategy-x",
        registered_spec_snapshot=RegisteredSpecSnapshot(
            instrument="BTCUSDT.P",
            base_timeframe=base_timeframe,
            raw_spec={},
            source_path="a.json",
        ),
        risk_multiplier="1",
        current_trade_cycle=current_trade_cycle,
    )


def _event(
    *,
    sid: str = _SID,
    trade_cycle_id: str = _TRADE_CYCLE_ID,
    first_fill_at_ms: int = _FIRST_FILL_AT_MS,
) -> AbiFirstFillExecutionEvent:
    return AbiFirstFillExecutionEvent(sid, trade_cycle_id, first_fill_at_ms)


def _frozen_context(*, first_fill_at_ms: int = _FIRST_FILL_AT_MS) -> FrozenExecutedEntryContext:
    return FrozenExecutedEntryContext(
        desired_entry=_desired_entry(),
        first_fill_at_ms=first_fill_at_ms,
        entry_bar_open_time_ms=_SOURCE_PLAN_BAR_OPEN_TIME_MS,
    )


def _is_key_locked(registry: StrategyInstanceKeyedMutexRegistry, sid: str) -> bool:
    """White-box probe of the real per-key lock's current hold state."""
    lock = registry._locks.get(sid)  # noqa: SLF001 - intentional white-box probe
    if lock is None:
        return False
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True


class _FakeRepository:
    """Repository recording get/save calls. Deliberately has no get_or_create
    method: if AbiExecutionEventOrchestrator ever called it, the call would
    raise AttributeError, failing the test loudly rather than silently."""

    def __init__(self, state: StrategyInstanceRuntimeState | None) -> None:
        self._state = state
        self.get_calls: list[str] = []
        self.save_calls: list[StrategyInstanceRuntimeState] = []

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        self.get_calls.append(strategy_instance_id)
        return self._state

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls.append(state)
        self._state = state
        return state


class _FailingSaveRepository(_FakeRepository):
    def __init__(self, state: StrategyInstanceRuntimeState, error: Exception) -> None:
        super().__init__(state)
        self._error = error

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls.append(state)
        raise self._error


class _LockCheckingRepository:
    """Repository whose get(...) records whether the real keyed lock is held
    at the moment it runs. Also has no get_or_create method."""

    def __init__(
        self,
        state: StrategyInstanceRuntimeState,
        registry: StrategyInstanceKeyedMutexRegistry,
        sid: str,
    ) -> None:
        self._state = state
        self._registry = registry
        self._sid = sid
        self.get_lock_states: list[bool] = []

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        self.get_lock_states.append(_is_key_locked(self._registry, self._sid))
        return self._state

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self._state = state
        return state


def _seed_repository_with_trade_cycle(sid: str) -> InMemoryStrategyInstanceRuntimeStateRepository:
    repo = InMemoryStrategyInstanceRuntimeStateRepository()
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
    return repo


# ---------------------------------------------------------------------------
# 3.1 / 3.2: Mutex key and ordering
# ---------------------------------------------------------------------------


def test_mutex_acquired_keyed_by_exact_strategy_instance_id() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()
    repo = _FakeRepository(None)
    orch = AbiExecutionEventOrchestrator(state_repository=repo, keyed_mutex_registry=registry)

    with pytest.raises(StrategyInstanceStateNotFound):
        orch.process(_event(sid=_SID))

    assert _SID in registry._locks  # noqa: SLF001
    assert repo.get_calls == [_SID]


def test_get_called_only_after_mutex_acquired() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()
    state = _runtime_state()
    repo = _LockCheckingRepository(state, registry, _SID)
    orch = AbiExecutionEventOrchestrator(state_repository=repo, keyed_mutex_registry=registry)

    assert _is_key_locked(registry, _SID) is False

    orch.process(_event())

    assert repo.get_lock_states == [True]
    assert _is_key_locked(registry, _SID) is False


# ---------------------------------------------------------------------------
# 3.3: get, never get_or_create
# ---------------------------------------------------------------------------


def test_get_is_used_and_get_or_create_is_never_called() -> None:
    """_FakeRepository has no get_or_create attribute; if process(...) tried
    to call it, this test would fail with AttributeError instead of passing
    silently."""
    state = _runtime_state()
    repo = _FakeRepository(state)
    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    orch.process(_event())

    assert repo.get_calls == [_SID]


# ---------------------------------------------------------------------------
# 3.4: Missing state fails closed without save
# ---------------------------------------------------------------------------


def test_missing_state_fails_closed_without_save() -> None:
    repo = _FakeRepository(None)
    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    with pytest.raises(StrategyInstanceStateNotFound):
        orch.process(_event())

    assert repo.save_calls == []


# ---------------------------------------------------------------------------
# 3.5: A confirmed freeze saves exactly once and returns save's exact result
# ---------------------------------------------------------------------------


def test_successful_freeze_saves_exactly_once_and_returns_saves_exact_result() -> None:
    state = _runtime_state()
    repo = _FakeRepository(state)
    sentinel_saved = object()
    repo.save = MagicMock(return_value=sentinel_saved)  # type: ignore[method-assign]

    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    result = orch.process(_event())

    assert repo.save.call_count == 1
    saved_argument = repo.save.call_args[0][0]
    assert saved_argument is not state
    assert saved_argument.current_trade_cycle.frozen_entry_context is not None
    assert result is sentinel_saved


# ---------------------------------------------------------------------------
# 3.6: Identical retry is a no-op, no save
# ---------------------------------------------------------------------------


def test_identical_retry_returns_same_object_and_skips_save() -> None:
    state = _runtime_state(frozen_entry_context=_frozen_context())
    repo = _FakeRepository(state)
    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    result = orch.process(_event(first_fill_at_ms=_FIRST_FILL_AT_MS))

    assert result is state
    assert repo.save_calls == []


# ---------------------------------------------------------------------------
# 3.7: A domain exception propagates without save
# ---------------------------------------------------------------------------


def test_domain_exception_propagates_without_save() -> None:
    state = _runtime_state(trade_cycle_id=None)
    repo = _FakeRepository(state)
    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    with pytest.raises(FirstFillInvariantError):
        orch.process(_event())

    assert repo.save_calls == []


def test_conflicting_retry_domain_exception_propagates_without_save() -> None:
    state = _runtime_state(frozen_entry_context=_frozen_context())
    repo = _FakeRepository(state)
    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    with pytest.raises(FirstFillInvariantError, match="already frozen"):
        orch.process(_event(first_fill_at_ms=_FIRST_FILL_AT_MS + 1_000))

    assert repo.save_calls == []


# ---------------------------------------------------------------------------
# 3.8: A save exception propagates after exactly one attempt
# ---------------------------------------------------------------------------


def test_save_exception_propagates_after_exactly_one_attempt() -> None:
    state = _runtime_state()
    sentinel = RuntimeError("save boom")
    repo = _FailingSaveRepository(state, sentinel)
    orch = AbiExecutionEventOrchestrator(
        state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
    )

    with pytest.raises(RuntimeError) as exc_info:
        orch.process(_event())

    assert exc_info.value is sentinel
    assert len(repo.save_calls) == 1


# ---------------------------------------------------------------------------
# 3.9: Mutex released after success and after any exception
# ---------------------------------------------------------------------------


class TestMutexRelease:
    def test_released_after_successful_freeze(self) -> None:
        registry = StrategyInstanceKeyedMutexRegistry()
        state = _runtime_state()
        repo = _FakeRepository(state)
        orch = AbiExecutionEventOrchestrator(state_repository=repo, keyed_mutex_registry=registry)

        orch.process(_event())

        with registry.hold(_SID):
            pass

    def test_released_after_identical_retry_noop(self) -> None:
        registry = StrategyInstanceKeyedMutexRegistry()
        state = _runtime_state(frozen_entry_context=_frozen_context())
        repo = _FakeRepository(state)
        orch = AbiExecutionEventOrchestrator(state_repository=repo, keyed_mutex_registry=registry)

        orch.process(_event(first_fill_at_ms=_FIRST_FILL_AT_MS))

        with registry.hold(_SID):
            pass

    @pytest.mark.parametrize(
        ("build_repo", "expected_error"),
        [
            (lambda: _FakeRepository(None), StrategyInstanceStateNotFound),
            (
                lambda: _FakeRepository(_runtime_state(trade_cycle_id=None)),
                FirstFillInvariantError,
            ),
            (
                lambda: _FailingSaveRepository(_runtime_state(), RuntimeError("boom")),
                RuntimeError,
            ),
        ],
        ids=["missing_state", "domain_exception", "save_exception"],
    )
    def test_released_after_any_exception(
        self, build_repo: Any, expected_error: type[Exception]
    ) -> None:
        registry = StrategyInstanceKeyedMutexRegistry()
        repo = build_repo()
        orch = AbiExecutionEventOrchestrator(state_repository=repo, keyed_mutex_registry=registry)

        with pytest.raises(expected_error):
            orch.process(_event())

        with registry.hold(_SID):
            pass


# ---------------------------------------------------------------------------
# 3.10: Constructor accepts exactly state_repository and keyed_mutex_registry
# ---------------------------------------------------------------------------


def test_constructor_accepts_exactly_state_repository_and_keyed_mutex_registry() -> None:
    signature = inspect.signature(AbiExecutionEventOrchestrator.__init__)
    param_names = list(signature.parameters)

    assert param_names == ["self", "state_repository", "keyed_mutex_registry"]
    for name in ("state_repository", "keyed_mutex_registry"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_constructor_rejects_an_unknown_collaborator() -> None:
    with pytest.raises(TypeError):
        AbiExecutionEventOrchestrator(  # type: ignore[call-arg]
            state_repository=_FakeRepository(None),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            strategy_engine=object(),
        )


# ---------------------------------------------------------------------------
# 3.11: Real integration -- InMemory repository, real mutex, real apply_first_fill
# ---------------------------------------------------------------------------


class TestRealIntegration:
    def test_first_successful_freeze_identical_retry_and_conflicting_retry(self) -> None:
        repo = _seed_repository_with_trade_cycle(_SID)
        orch = AbiExecutionEventOrchestrator(
            state_repository=repo, keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry()
        )

        first = orch.process(_event())
        assert first.current_trade_cycle is not None
        context = first.current_trade_cycle.frozen_entry_context
        assert context is not None
        assert context.first_fill_at_ms == _FIRST_FILL_AT_MS
        assert context.entry_bar_open_time_ms == _SOURCE_PLAN_BAR_OPEN_TIME_MS

        retried = orch.process(_event())
        assert retried is first

        with pytest.raises(FirstFillInvariantError, match="already frozen"):
            orch.process(_event(first_fill_at_ms=_FIRST_FILL_AT_MS + 1_000))

        assert repo.get(_SID) == first
