"""Focused Runtime orchestrator sequencing, persistence, branch, and error tests."""

from __future__ import annotations

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
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupResponse,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.resolver import OpenPositionResolver
from strategy_runtime.runtime.orchestrator.errors import UnknownStrategyProjectionError
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.position_management_orchestrator import (
    PositionManagementOrchestrator,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import (
    CloseSignal,
    DesiredProtection,
    PositionManagementRecipe,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
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
    first_fill_at_ms: int = 950,
) -> PositionResolvedStrategyInstanceRuntimeState:
    target = state or _runtime_state()
    response = (
        OpenPositionLookupResponse(True, first_fill_at_ms, "100.5")
        if position_open
        else OpenPositionLookupResponse(False)
    )
    return OpenPositionResolver(_Abi(response)).resolve(target)


def _open_trade_state(*, frozen: bool, first_fill_at_ms: int = 950) -> StrategyInstanceRuntimeState:
    """A runtime state with a current trade cycle, optionally already frozen.

    ``first_fill_at_ms=300_950`` aligns to a non-zero 5m candle boundary
    (300_000) that is not before ``_desired_entry()``'s
    ``source_plan_bar_open_time_ms`` (900), so a fresh freeze through
    ``apply_first_fill`` succeeds for that value.
    """
    cycle = CurrentTradeCycle(
        "cycle-1",
        AppliedEntryPackage(
            applied_desired_entry=_desired_entry(),
            calculated_quantity="0.1",
        ),
        frozen_entry_context=(
            FrozenExecutedEntryContext(
                desired_entry=_desired_entry(),
                first_fill_at_ms=first_fill_at_ms,
                entry_bar_open_time_ms=900,
            )
            if frozen
            else None
        ),
    )
    return replace(_runtime_state(), current_trade_cycle=cycle)


def _open_trade_projection(
    item: PositionResolvedStrategyInstance,
    *,
    desired_protection: DesiredProtection | None = None,
    close_active: bool = False,
) -> OpenTradeProjectedStrategyInstance:
    recipe = PositionManagementRecipe(
        desired_protection=desired_protection or DesiredProtection("99", "103"),
        close_signal=CloseSignal(close_active),
        diagnostics={},
    )
    return OpenTradeProjectedStrategyInstance(item, recipe)


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


class _FakePositionManagementExecutionPort:
    def __init__(
        self,
        *,
        protection_confirmation: ProtectionAppliedConfirmation | None = None,
        close_confirmation: PositionClosedConfirmation | None = None,
        error: Exception | None = None,
    ) -> None:
        self.protection_confirmation = protection_confirmation
        self.close_confirmation = close_confirmation
        self.error = error
        self.apply_calls: list[ApplyProtectionCommand] = []
        self.close_calls: list[ClosePositionCommand] = []

    def apply_protection(self, command: ApplyProtectionCommand) -> ProtectionAppliedConfirmation:
        self.apply_calls.append(command)
        if self.error is not None:
            raise self.error
        assert self.protection_confirmation is not None
        return self.protection_confirmation

    def close_position(self, command: ClosePositionCommand) -> PositionClosedConfirmation:
        self.close_calls.append(command)
        if self.error is not None:
            raise self.error
        assert self.close_confirmation is not None
        return self.close_confirmation


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
        saved = replace(state)
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


# ---------------------------------------------------------------------------
# 4. Sequencing and Persistence Tests
# ---------------------------------------------------------------------------


def _is_key_locked(registry: StrategyInstanceKeyedMutexRegistry, sid: str) -> bool:
    """White-box probe of the real per-key lock's current hold state.

    A non-blocking acquire attempt on the exact lock the production
    ``hold(...)`` context manager uses proves whether the critical section is
    genuinely held at the moment a collaborator is invoked - not merely that
    ``hold()`` was called at some earlier point.
    """
    lock = registry._locks.get(sid)  # noqa: SLF001 - intentional white-box probe
    if lock is None:
        return False
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True


class _LockCheckingRepository:
    """Repository whose get_or_create/save assert the real keyed lock is held."""

    def __init__(
        self,
        state: StrategyInstanceRuntimeState,
        registry: StrategyInstanceKeyedMutexRegistry,
        sid: str,
    ) -> None:
        self._state = state
        self._registry = registry
        self._sid = sid
        self.get_or_create_lock_states: list[bool] = []
        self.save_lock_states: list[bool] = []

    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState:
        self.get_or_create_lock_states.append(_is_key_locked(self._registry, self._sid))
        return self._state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._state if strategy_instance_id == self._sid else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_lock_states.append(_is_key_locked(self._registry, self._sid))
        self._state = state
        return state


class _LockCheckingResolver:
    """Resolver whose resolve asserts the real keyed lock is held."""

    def __init__(
        self,
        resolved: PositionResolvedStrategyInstanceRuntimeState,
        registry: StrategyInstanceKeyedMutexRegistry,
        sid: str,
    ) -> None:
        self._resolved = resolved
        self._registry = registry
        self._sid = sid
        self.lock_states: list[bool] = []

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        self.lock_states.append(_is_key_locked(self._registry, self._sid))
        return self._resolved


class _LockCheckingRouter:
    """Router whose route asserts the real keyed lock is held."""

    def __init__(
        self,
        projected: LiveEntryProjectedStrategyInstance,
        registry: StrategyInstanceKeyedMutexRegistry,
        sid: str,
    ) -> None:
        self._projected = projected
        self._registry = registry
        self._sid = sid
        self.lock_states: list[bool] = []

    def route(self, item: PositionResolvedStrategyInstance) -> LiveEntryProjectedStrategyInstance:
        self.lock_states.append(_is_key_locked(self._registry, self._sid))
        return self._projected


class _LockCheckingExecutionPort:
    """Execution port whose execute asserts the real keyed lock is held."""

    def __init__(self, registry: StrategyInstanceKeyedMutexRegistry, sid: str) -> None:
        self._registry = registry
        self._sid = sid
        self.lock_states: list[bool] = []

    def execute(self, command: Any, source_state: Any) -> EntryAppliedConfirmation:
        self.lock_states.append(_is_key_locked(self._registry, self._sid))
        return EntryAppliedConfirmation(
            strategy_instance_id=source_state.strategy_instance_id,
            trade_cycle_id=command.trade_cycle_id,
            applied_desired_entry=command.desired_entry,
            calculated_quantity="0.5",
        )


class TestSequencingAndPersistence:
    def test_mutex_acquired_before_state_load(self) -> None:
        """4.1: the real per-key lock is already held at the moment
        get_or_create runs, and released once process(...) returns."""
        registry = StrategyInstanceKeyedMutexRegistry()
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, None)

        assert _is_key_locked(registry, _SID) is False

        repo = _LockCheckingRepository(state, registry, _SID)
        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=registry,
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        orch.process(unit)

        assert repo.get_or_create_lock_states == [True]
        assert _is_key_locked(registry, _SID) is False

    def test_mutex_held_through_all_stages(self) -> None:
        """4.2: the same real per-key lock stays held across get_or_create,
        resolve, route, reconciliation execute, and save."""
        registry = StrategyInstanceKeyedMutexRegistry()
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        repo = _LockCheckingRepository(state, registry, _SID)
        resolver = _LockCheckingResolver(resolved, registry, _SID)
        router = _LockCheckingRouter(projected, registry, _SID)
        execution_port = _LockCheckingExecutionPort(registry, _SID)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=resolver,
            use_case_router=router,
            keyed_mutex_registry=registry,
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=execution_port,
            ),
        )

        orch.process(unit)

        assert repo.get_or_create_lock_states == [True]
        assert resolver.lock_states == [True]
        assert router.lock_states == [True]
        assert execution_port.lock_states == [True]
        assert repo.save_lock_states == [True]
        assert _is_key_locked(registry, _SID) is False

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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
        saved_return = replace(state)
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
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_ApplyExecutionPort(),
            ),
        )

        result = orch.process(unit)
        assert result is saved_return

    def test_no_reload_or_second_argument_for_reconciliation(self) -> None:
        """4.7: the top-level orchestrator does not reload state for
        reconciliation and does not pass state as a second nested-operation
        argument. A fake whose execute(...) accepts exactly one argument
        makes any second-argument call fail with TypeError rather than
        silently succeed."""
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())

        repo = _FakeRepository(state)
        call_args: list[LiveEntryProjectedStrategyInstance] = []

        class _SingleArgumentReconciliation:
            def execute(
                self, projection: LiveEntryProjectedStrategyInstance
            ) -> StrategyInstanceRuntimeState:
                call_args.append(projection)
                return state

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=_SingleArgumentReconciliation(),
        )

        result = orch.process(unit)

        assert call_args == [projected]
        assert repo.get_or_create_calls == ["get_or_create"]
        assert repo.save_calls == []
        assert result == state


# ---------------------------------------------------------------------------
# 5. Concurrency and Release Tests
# ---------------------------------------------------------------------------


class TestConcurrencyAndRelease:
    """5.1/5.2/5.3 (deterministic same- and different-instance overlap
    proofs) live in test_concurrency.py; this class covers 5.4/5.5/5.6
    mutex-release behavior only, using the real registry directly."""

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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
            (lambda: RuntimeError("position management failed"), "position_management"),
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

        if error_label == "position_management":
            projection: Any = _open_trade_projection(item)
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
        else:
            ep = _FakeExecutionPort()

        entry_orch = EntryReconciliationOrchestrator(
            trade_cycle_id_factory=lambda: "tc-id",
            execution_port=ep,
        )
        position_management_orchestrator = MagicMock()
        if error_label == "position_management":
            position_management_orchestrator.execute.side_effect = error

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=resolver,
            use_case_router=use_case_router,
            keyed_mutex_registry=real,
            position_management_orchestrator=position_management_orchestrator,
            entry_reconciliation_orchestrator=entry_orch,
        )

        with pytest.raises(type(error)):
            orch.process(unit)

        with real.hold(_SID):
            pass


# ---------------------------------------------------------------------------
# 6. Typed Branch and Error-Boundary Tests
# ---------------------------------------------------------------------------


class _SentinelError(Exception):
    """Distinct marker exception used to prove identity-preserving propagation."""


class _CountingRepository:
    """Repository recording exact get_or_create/save call counts."""

    def __init__(
        self,
        state: StrategyInstanceRuntimeState,
        *,
        get_or_create_error: Exception | None = None,
        save_error: Exception | None = None,
    ) -> None:
        self._state = state
        self._get_or_create_error = get_or_create_error
        self._save_error = save_error
        self.get_or_create_call_count = 0
        self.save_call_count = 0

    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState:
        self.get_or_create_call_count += 1
        if self._get_or_create_error is not None:
            raise self._get_or_create_error
        return self._state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._state if strategy_instance_id == self._state.strategy_instance_id else None

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_call_count += 1
        if self._save_error is not None:
            raise self._save_error
        return state


class _CountingResolver:
    """Resolver recording exact resolve call count."""

    def __init__(
        self,
        *,
        resolved: PositionResolvedStrategyInstanceRuntimeState | None = None,
        error: Exception | None = None,
    ) -> None:
        self._resolved = resolved
        self._error = error
        self.call_count = 0

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        assert self._resolved is not None
        return self._resolved


class _CountingRouter:
    """Router recording exact route call count."""

    def __init__(
        self,
        *,
        projected: LiveEntryProjectedStrategyInstance | None = None,
        error: Exception | None = None,
    ) -> None:
        self._projected = projected
        self._error = error
        self.call_count = 0

    def route(self, item: PositionResolvedStrategyInstance) -> LiveEntryProjectedStrategyInstance:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        assert self._projected is not None
        return self._projected


class _CountingReconciliation:
    """Nested reconciliation orchestrator recording exact execute call count."""

    def __init__(
        self,
        *,
        result: StrategyInstanceRuntimeState | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.call_count = 0

    def execute(
        self, projection: LiveEntryProjectedStrategyInstance
    ) -> StrategyInstanceRuntimeState:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class TestTypedBranchAndErrorBoundary:
    def test_open_trade_noop_returns_source_without_post_projection_save(self) -> None:
        state = _open_trade_state(frozen=True)
        resolved = _resolved_state(position_open=True, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projection = _open_trade_projection(item)
        repo = _FakeRepository(state)
        port = _FakePositionManagementExecutionPort()
        position_orch = PositionManagementOrchestrator(port)
        real_execute = position_orch.execute
        received: list[OpenTradeProjectedStrategyInstance] = []

        def _tracked_execute(
            exact_projection: OpenTradeProjectedStrategyInstance,
        ) -> StrategyInstanceRuntimeState:
            received.append(exact_projection)
            return real_execute(exact_projection)

        position_orch.execute = _tracked_execute  # type: ignore[method-assign]

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projection)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=position_orch,
            entry_reconciliation_orchestrator=MagicMock(),
        )

        result = orch.process(unit)

        assert result is state
        assert received == [projection]
        assert port.apply_calls == []
        assert port.close_calls == []
        assert repo.save_calls == []

    def test_open_trade_apply_protection_saves_confirmed_replacement_once(self) -> None:
        state = _open_trade_state(frozen=True)
        resolved = _resolved_state(position_open=True, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        desired_protection = DesiredProtection("98", "103")
        projection = _open_trade_projection(item, desired_protection=desired_protection)
        repo = _FakeRepository(state)
        port = _FakePositionManagementExecutionPort(
            protection_confirmation=ProtectionAppliedConfirmation(
                _SID, "cycle-1", desired_protection
            )
        )

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projection)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=PositionManagementOrchestrator(port),
            entry_reconciliation_orchestrator=MagicMock(),
        )

        result = orch.process(unit)

        assert len(port.apply_calls) == 1
        assert port.close_calls == []
        assert len(repo.save_calls) == 1
        assert result is repo.save_calls[0]
        assert result.current_trade_cycle is not None
        assert (
            result.current_trade_cycle.latest_confirmed_management_protection == desired_protection
        )

    def test_open_trade_close_position_saves_cleared_cycle_once(self) -> None:
        state = _open_trade_state(frozen=True)
        resolved = _resolved_state(position_open=True, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projection = _open_trade_projection(item, close_active=True)
        repo = _FakeRepository(state)
        port = _FakePositionManagementExecutionPort(
            close_confirmation=PositionClosedConfirmation(_SID, "cycle-1")
        )

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projection)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=PositionManagementOrchestrator(port),
            entry_reconciliation_orchestrator=MagicMock(),
        )

        result = orch.process(unit)

        assert port.apply_calls == []
        assert len(port.close_calls) == 1
        assert len(repo.save_calls) == 1
        assert result is repo.save_calls[0]
        assert result.current_trade_cycle is None

    def test_position_management_failure_preserves_first_fill_freeze_only(self) -> None:
        state = _open_trade_state(frozen=False)
        resolved = _resolved_state(position_open=True, state=state, first_fill_at_ms=300_950)
        unit = _processing_unit()
        repo = _FakeRepository(state)
        router = MagicMock(
            route=MagicMock(
                side_effect=lambda item: _open_trade_projection(item, close_active=True)
            )
        )
        error = RuntimeError("position-management execution failed")
        port = _FakePositionManagementExecutionPort(error=error)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=router,
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=PositionManagementOrchestrator(port),
            entry_reconciliation_orchestrator=MagicMock(),
        )

        with pytest.raises(RuntimeError) as raised:
            orch.process(unit)

        assert raised.value is error
        assert len(port.close_calls) == 1
        assert len(repo.save_calls) == 1
        frozen_state = repo.save_calls[0]
        assert repo._state is frozen_state
        assert frozen_state.current_trade_cycle is not None
        assert frozen_state.current_trade_cycle.frozen_entry_context is not None
        assert frozen_state.current_trade_cycle.frozen_entry_context.first_fill_at_ms == 300_950
        routed_item = router.route.call_args.args[0]
        assert routed_item.resolved_state.runtime_state is frozen_state

    def test_open_trade_freeze_conflict_propagates_without_routing(self) -> None:
        state = _open_trade_state(frozen=True, first_fill_at_ms=950)
        resolved = _resolved_state(position_open=True, state=state, first_fill_at_ms=951)
        unit = _processing_unit()
        repo = _FakeRepository(state)
        router = MagicMock()

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=router,
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        with pytest.raises(FirstFillInvariantError):
            orch.process(unit)

        assert repo.save_calls == []
        router.route.assert_not_called()

    def test_closed_position_skips_first_fill_freeze(self) -> None:
        """A mid-cycle instance not yet reported open by ABI never touches
        the first-fill transition; live-entry routing proceeds unchanged."""
        state = _open_trade_state(frozen=False)
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        repo = _FakeRepository(state)
        projection = LiveEntryProjectedStrategyInstance(
            PositionResolvedStrategyInstance(unit, resolved), _desired_entry()
        )

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projection)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=MagicMock(execute=MagicMock(return_value=state)),
        )

        result = orch.process(unit)
        assert result is state
        assert repo.save_calls == []

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
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=ep,
            ),
        )

        with pytest.raises(UnknownStrategyProjectionError):
            orch.process(unit)
        assert ep.calls == []
        assert repo.save_calls == []

    def test_get_or_create_error_propagates_with_zero_downstream_calls(self) -> None:
        """6.3/6.4: get_or_create failure -> resolve=0, route=0,
        reconciliation=0, save=0, and the exact raised exception propagates."""
        sentinel = _SentinelError("get_or_create boom")
        state = _runtime_state()
        repo = _CountingRepository(state, get_or_create_error=sentinel)
        resolver = _CountingResolver()
        router = _CountingRouter()
        reconciliation = _CountingReconciliation()

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=resolver,
            use_case_router=router,
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=reconciliation,
        )

        with pytest.raises(_SentinelError) as exc_info:
            orch.process(_processing_unit())

        assert exc_info.value is sentinel
        assert resolver.call_count == 0
        assert router.call_count == 0
        assert reconciliation.call_count == 0
        assert repo.save_call_count == 0

    def test_resolver_error_propagates_with_zero_downstream_calls(self) -> None:
        """6.3/6.4: resolver failure -> route=0, reconciliation=0, save=0."""
        sentinel = _SentinelError("resolver boom")
        state = _runtime_state()
        repo = _CountingRepository(state)
        resolver = _CountingResolver(error=sentinel)
        router = _CountingRouter()
        reconciliation = _CountingReconciliation()

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=resolver,
            use_case_router=router,
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=reconciliation,
        )

        with pytest.raises(_SentinelError) as exc_info:
            orch.process(_processing_unit())

        assert exc_info.value is sentinel
        assert repo.get_or_create_call_count == 1
        assert router.call_count == 0
        assert reconciliation.call_count == 0
        assert repo.save_call_count == 0

    def test_router_engine_error_propagates_with_zero_downstream_calls(self) -> None:
        """6.3/6.4: router/Engine failure -> reconciliation=0, save=0."""
        sentinel = _SentinelError("engine boom")
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        repo = _CountingRepository(state)
        resolver = _CountingResolver(resolved=resolved)
        router = _CountingRouter(error=sentinel)
        reconciliation = _CountingReconciliation()

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=resolver,
            use_case_router=router,
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=reconciliation,
        )

        with pytest.raises(_SentinelError) as exc_info:
            orch.process(_processing_unit())

        assert exc_info.value is sentinel
        assert resolver.call_count == 1
        assert reconciliation.call_count == 0
        assert repo.save_call_count == 0

    def test_reconciliation_error_propagates_with_zero_save_calls(self) -> None:
        """6.3/6.4: reconciliation failure -> execute=1, save=0."""
        sentinel = _SentinelError("reconciliation boom")
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())
        repo = _CountingRepository(state)
        reconciliation = _CountingReconciliation(error=sentinel)

        orch = StrategyRuntimeOrchestrator(
            state_repository=repo,
            open_position_resolver=MagicMock(resolve=MagicMock(return_value=resolved)),
            use_case_router=MagicMock(route=MagicMock(return_value=projected)),
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=reconciliation,
        )

        with pytest.raises(_SentinelError) as exc_info:
            orch.process(unit)

        assert exc_info.value is sentinel
        assert reconciliation.call_count == 1
        assert repo.save_call_count == 0

    def test_save_error_propagates_after_exactly_one_attempt_no_retry(self) -> None:
        """6.3/6.4: save failure -> exactly one save attempt, no retry, and
        the exact exception raised by save(...) propagates by identity."""
        sentinel = _SentinelError("save boom")
        state = _runtime_state()
        resolved = _resolved_state(position_open=False, state=state)
        unit = _processing_unit()
        item = PositionResolvedStrategyInstance(unit, resolved)
        projected = LiveEntryProjectedStrategyInstance(item, _desired_entry())
        repo = _CountingRepository(state, save_error=sentinel)

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
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_ApplyExecutionPort(),
            ),
        )

        with pytest.raises(_SentinelError) as exc_info:
            orch.process(unit)

        assert exc_info.value is sentinel
        assert repo.save_call_count == 1

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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
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
            position_management_orchestrator=MagicMock(),
            entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
                trade_cycle_id_factory=lambda: "tc-id",
                execution_port=_FakeExecutionPort(),
            ),
        )

        result = orch.dispatch(unit)
        assert isinstance(result, StrategyCycleDispatchOutcome)
        assert not isinstance(result, StrategyInstanceRuntimeState)
