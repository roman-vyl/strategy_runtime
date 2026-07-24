"""Open-position resolver application service."""

from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupRequest,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.ports import AbiOpenPositionLookupPort
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState


class OpenPositionResolver:
    def __init__(self, abi_lookup: AbiOpenPositionLookupPort) -> None:
        self._abi_lookup = abi_lookup

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        response = self._abi_lookup.lookup(OpenPositionLookupRequest(state.strategy_instance_id))
        return PositionResolvedStrategyInstanceRuntimeState(
            runtime_state=state,
            position_open=response.position_open,
            entry_bar_open_time_ms=response.entry_bar_open_time_ms,
            executed_entry_price=response.executed_entry_price,
        )
