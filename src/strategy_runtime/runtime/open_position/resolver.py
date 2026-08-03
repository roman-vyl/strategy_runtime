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
        current_trade_cycle = state.current_trade_cycle
        if current_trade_cycle is None:
            return PositionResolvedStrategyInstanceRuntimeState(
                runtime_state=state,
                position_open=False,
                first_fill_at_ms=None,
                average_entry_price=None,
            )

        response = self._abi_lookup.lookup(
            OpenPositionLookupRequest(
                strategy_instance_id=state.strategy_instance_id,
                trade_cycle_id=current_trade_cycle.trade_cycle_id,
            )
        )
        return PositionResolvedStrategyInstanceRuntimeState(
            runtime_state=state,
            position_open=response.position_open,
            first_fill_at_ms=response.first_fill_at_ms,
            average_entry_price=response.average_entry_price,
        )
