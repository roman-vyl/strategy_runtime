"""Semantic Strategy Runtime orchestrator through final aggregate application."""

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.ports import OpenPositionResolverPort
from strategy_runtime.runtime.orchestrator.errors import (
    OpenTradeProjectionUnsupportedError,
    UnknownStrategyProjectionError,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.routing.ports import StrategyUseCaseRouterPort
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.utility.committed_bar.models import (
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification


class StrategyRuntimeOrchestrator:
    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        open_position_resolver: OpenPositionResolverPort,
        use_case_router: StrategyUseCaseRouterPort,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        entry_reconciliation_orchestrator: EntryReconciliationOrchestrator,
    ) -> None:
        self._state_repository = state_repository
        self._open_position_resolver = open_position_resolver
        self._use_case_router = use_case_router
        self._keyed_mutex_registry = keyed_mutex_registry
        self._entry_reconciliation_orchestrator = entry_reconciliation_orchestrator

    def process(
        self, unit: StrategyBarProcessingUnit[DeploymentSpecification]
    ) -> StrategyInstanceRuntimeState:
        with self._keyed_mutex_registry.hold(unit.strategy_instance_id):
            state = self._state_repository.get_or_create(
                GetOrCreateStrategyInstanceRuntimeStateRequest(
                    strategy_instance_id=unit.strategy_instance_id,
                    strategy_id=unit.deployment.strategy_id,
                    instrument=unit.deployment.instrument,
                    base_timeframe=unit.deployment.base_timeframe,
                    raw_spec=unit.deployment.raw_spec,
                    source_path=unit.deployment.source_path,
                )
            )
            resolved = self._open_position_resolver.resolve(state)
            projection = self._use_case_router.route(
                PositionResolvedStrategyInstance(unit, resolved)
            )

            if type(projection) is LiveEntryProjectedStrategyInstance:
                source_state = projection.source.resolved_state.runtime_state
                resulting_state = self._entry_reconciliation_orchestrator.execute(projection)
                if resulting_state == source_state:
                    return resulting_state
                saved_state = self._state_repository.save(resulting_state)
                return saved_state

            if type(projection) is OpenTradeProjectedStrategyInstance:
                raise OpenTradeProjectionUnsupportedError

            raise UnknownStrategyProjectionError

    def dispatch(
        self, unit: StrategyBarProcessingUnit[DeploymentSpecification]
    ) -> StrategyCycleDispatchOutcome:
        self.process(unit)
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)
