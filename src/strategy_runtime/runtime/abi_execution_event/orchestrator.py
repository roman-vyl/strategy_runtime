"""Thin sequencing orchestrator applying an ABI first-fill execution event."""

from strategy_runtime.runtime.abi_execution_event.models import AbiFirstFillExecutionEvent
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.first_fill.freezer import FirstFillFreezer
from strategy_runtime.runtime.state.errors import StrategyInstanceStateNotFound
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository


class AbiExecutionEventOrchestrator:
    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        first_fill_freezer: FirstFillFreezer | None = None,
    ) -> None:
        self._state_repository = state_repository
        self._keyed_mutex_registry = keyed_mutex_registry
        self._first_fill_freezer = first_fill_freezer or FirstFillFreezer()

    def process(self, event: AbiFirstFillExecutionEvent) -> StrategyInstanceRuntimeState:
        with self._keyed_mutex_registry.hold(event.strategy_instance_id):
            state = self._state_repository.get(event.strategy_instance_id)
            if state is None:
                raise StrategyInstanceStateNotFound(event.strategy_instance_id)

            resulting_state = self._first_fill_freezer.freeze(
                state, event.trade_cycle_id, event.first_fill_at_ms
            )
            if resulting_state is state:
                return state

            return self._state_repository.save(resulting_state)
