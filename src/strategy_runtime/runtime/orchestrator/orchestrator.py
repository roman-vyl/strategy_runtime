"""Semantic Strategy Runtime orchestrator through Engine projection response."""

from strategy_runtime.runtime.open_position.ports import OpenPositionResolverPort
from strategy_runtime.runtime.routing.models import (
    PositionResolvedStrategyInstance,
    StrategyUseCaseProjectedInstance,
)
from strategy_runtime.runtime.routing.ports import StrategyUseCaseRouterPort
from strategy_runtime.runtime.state.models import GetOrCreateStrategyInstanceRuntimeStateRequest
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
    ) -> None:
        self._state_repository = state_repository
        self._open_position_resolver = open_position_resolver
        self._use_case_router = use_case_router

    def process(
        self, unit: StrategyBarProcessingUnit[DeploymentSpecification]
    ) -> StrategyUseCaseProjectedInstance:
        deployment = unit.deployment
        state = self._state_repository.get_or_create(
            GetOrCreateStrategyInstanceRuntimeStateRequest(
                strategy_instance_id=unit.strategy_instance_id,
                strategy_id=deployment.strategy_id,
                instrument=deployment.instrument,
                base_timeframe=deployment.base_timeframe,
                raw_spec=deployment.raw_spec,
                source_path=deployment.source_path,
            )
        )
        resolved = self._open_position_resolver.resolve(state)
        return self._use_case_router.route(PositionResolvedStrategyInstance(unit, resolved))

    def dispatch(
        self, unit: StrategyBarProcessingUnit[DeploymentSpecification]
    ) -> StrategyCycleDispatchOutcome:
        self.process(unit)
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)
