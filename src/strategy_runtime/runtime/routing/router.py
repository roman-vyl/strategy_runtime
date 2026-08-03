"""Live-entry/open-trade use-case router."""

from strategy_runtime.runtime.engine.live_entry import (
    LiveEntryProjectionRequest,
    StrategyEngineLiveEntryPort,
)
from strategy_runtime.runtime.engine.open_trade import StrategyEngineOpenTradePort
from strategy_runtime.runtime.routing.errors import (
    OpenTradeContextUnavailable,
    StrategyInstanceBindingError,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
    StrategyUseCaseProjectedInstance,
)


class StrategyUseCaseRouter:
    def __init__(
        self,
        *,
        live_entry_engine: StrategyEngineLiveEntryPort,
        open_trade_engine: StrategyEngineOpenTradePort,
    ) -> None:
        self._live_entry_engine = live_entry_engine
        self._open_trade_engine = open_trade_engine

    def route(self, item: PositionResolvedStrategyInstance) -> StrategyUseCaseProjectedInstance:
        unit = item.processing_unit
        deployment = unit.deployment
        resolved = item.resolved_state
        self._validate_instance_binding(item)
        if resolved.position_open:
            raise OpenTradeContextUnavailable(unit.strategy_instance_id)

        live_request = LiveEntryProjectionRequest(
            strategy_id=deployment.strategy_id,
            raw_spec=deployment.raw_spec,
            ticker=deployment.instrument,
            base_timeframe=deployment.base_timeframe,
            target_bar_open_time_ms=unit.committed_bar.open_time_ms,
        )
        live_response = self._live_entry_engine.project_live_entry(live_request)
        return LiveEntryProjectedStrategyInstance(
            source=item,
            desired_entry=live_response.desired_entry,
        )

    @staticmethod
    def _validate_instance_binding(item: PositionResolvedStrategyInstance) -> None:
        unit_instance_id = item.processing_unit.strategy_instance_id
        deployment_instance_id = item.processing_unit.deployment.strategy_instance_id
        state_instance_id = item.resolved_state.runtime_state.strategy_instance_id
        if unit_instance_id != deployment_instance_id:
            raise StrategyInstanceBindingError(
                "processing unit and deployment strategy_instance_id mismatch"
            )
        if unit_instance_id != state_instance_id:
            raise StrategyInstanceBindingError(
                "processing unit and runtime state strategy_instance_id mismatch"
            )
