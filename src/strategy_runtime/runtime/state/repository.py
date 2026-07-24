"""Strategy-instance runtime-state repository port and in-memory implementation."""

from threading import RLock
from typing import Protocol

from strategy_runtime.runtime.state.errors import StrategyInstanceIdentityConflict
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)


class StrategyInstanceRuntimeStateRepository(Protocol):
    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState: ...


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
            )
            self._states[request.strategy_instance_id] = state
            return state
