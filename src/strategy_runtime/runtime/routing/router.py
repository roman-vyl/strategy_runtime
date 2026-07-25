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
        if not resolved.position_open:
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

        cycle = resolved.runtime_state.current_trade_cycle
        if (
            cycle is None
            or not cycle.desired_entry_frozen
            or resolved.entry_bar_open_time_ms is None
            or resolved.executed_entry_price is None
        ):
            raise OpenTradeContextUnavailable(unit.strategy_instance_id)
        open_trade_request = OpenTradeProjectionRequest(
            strategy_id=deployment.strategy_id,
            raw_spec=deployment.raw_spec,
            ticker=deployment.instrument,
            base_timeframe=deployment.base_timeframe,
            target_bar_open_time_ms=unit.committed_bar.open_time_ms,
            desired_entry=cycle.desired_entry,
            entry_bar_open_time_ms=resolved.entry_bar_open_time_ms,
        )
        open_trade_response = self._open_trade_engine.project_open_trade(open_trade_request)
        return OpenTradeProjectedStrategyInstance(
            source=item,
            position_management_recipe=PositionManagementRecipe(
                desired_protection=open_trade_response.desired_protection,
                close_signal=open_trade_response.close_signal,
                diagnostics=open_trade_response.diagnostics,
            ),
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
