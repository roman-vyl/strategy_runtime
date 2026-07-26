"""Strategy-instance runtime-state repository port and in-memory implementation."""

from threading import RLock
from typing import Protocol

from strategy_runtime.runtime.state.errors import (
    StrategyInstanceIdentityConflict,
    StrategyInstanceRegistrationConflict,
    StrategyInstanceStateNotFound,
)
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)

_CANONICAL_INITIAL_RISK_MULTIPLIER = "1"


class StrategyInstanceRuntimeStateRepository(Protocol):
    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState: ...

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None: ...

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState: ...


class InMemoryStrategyInstanceRuntimeStateRepository:
    """Atomic deterministic implementation used by composition/tests until SQLite design."""

    def __init__(self) -> None:
        self._states: dict[str, StrategyInstanceRuntimeState] = {}
        self._lock = RLock()

    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState:
        with self._lock:
            existing = self._states.get(request.strategy_instance_id)
            if existing is not None:
                if existing.strategy_id != request.strategy_id:
                    raise StrategyInstanceIdentityConflict(request.strategy_instance_id)
                return existing
            state = StrategyInstanceRuntimeState(
                strategy_instance_id=request.strategy_instance_id,
                strategy_id=request.strategy_id,
                registered_spec_snapshot=RegisteredSpecSnapshot(
                    instrument=request.instrument,
                    base_timeframe=request.base_timeframe,
                    raw_spec=request.raw_spec,
                    source_path=request.source_path,
                ),
                risk_multiplier=_CANONICAL_INITIAL_RISK_MULTIPLIER,
            )
            self._states[request.strategy_instance_id] = state
            return state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        _require_strategy_instance_id(strategy_instance_id)
        with self._lock:
            return self._states.get(strategy_instance_id)

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        if type(state) is not StrategyInstanceRuntimeState:
            raise TypeError("state must be StrategyInstanceRuntimeState")
        with self._lock:
            existing = self._states.get(state.strategy_instance_id)
            if existing is None:
                raise StrategyInstanceStateNotFound(state.strategy_instance_id)
            if existing.strategy_id != state.strategy_id:
                raise StrategyInstanceIdentityConflict(state.strategy_instance_id)
            if existing.registered_spec_snapshot != state.registered_spec_snapshot:
                raise StrategyInstanceRegistrationConflict(state.strategy_instance_id)
            self._states[state.strategy_instance_id] = state
            return state


def _require_strategy_instance_id(strategy_instance_id: str) -> None:
    if type(strategy_instance_id) is not str or len(strategy_instance_id) == 0:
        raise ValueError("strategy_instance_id must be a non-empty string")
