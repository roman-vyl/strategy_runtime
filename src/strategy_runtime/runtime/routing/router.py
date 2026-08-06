"""Live-entry/open-trade use-case router."""

from strategy_runtime.runtime.engine.live_entry import (
    LiveEntryProjectionRequest,
    StrategyEngineLiveEntryPort,
)
from strategy_runtime.runtime.engine.open_trade import (
    OpenTradeProjectionRequest,
    StrategyEngineOpenTradePort,
)
from strategy_runtime.runtime.recipes.position_management import PositionManagementRecipe
from strategy_runtime.runtime.routing.errors import (
    OpenTradeContextUnavailable,
    StrategyInstanceBindingError,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
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
            return self._route_open_trade(item)

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

    def _route_open_trade(
        self, item: PositionResolvedStrategyInstance
    ) -> OpenTradeProjectedStrategyInstance:
        unit = item.processing_unit
        resolved = item.resolved_state
        runtime_state = resolved.runtime_state
        current_cycle = runtime_state.current_trade_cycle
        frozen_context = current_cycle.frozen_entry_context if current_cycle is not None else None
        if frozen_context is None:
            raise OpenTradeContextUnavailable(unit.strategy_instance_id)

        snapshot = runtime_state.registered_spec_snapshot
        open_trade_request = OpenTradeProjectionRequest(
            strategy_id=runtime_state.strategy_id,
            raw_spec=snapshot.raw_spec,
            ticker=snapshot.instrument,
            base_timeframe=snapshot.base_timeframe,
            target_bar_open_time_ms=unit.committed_bar.open_time_ms,
            desired_entry=frozen_context.desired_entry,
            entry_bar_open_time_ms=frozen_context.entry_bar_open_time_ms,
        )
        open_response = self._open_trade_engine.project_open_trade(open_trade_request)
        recipe = PositionManagementRecipe(
            desired_protection=open_response.desired_protection,
            close_signal=open_response.close_signal,
            diagnostics=open_response.diagnostics,
        )
        return OpenTradeProjectedStrategyInstance(source=item, position_management_recipe=recipe)

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
