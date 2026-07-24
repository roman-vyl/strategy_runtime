"""Open-position resolver ports."""

from typing import Protocol

from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupRequest,
    OpenPositionLookupResponse,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState


class AbiOpenPositionLookupPort(Protocol):
    def lookup(self, request: OpenPositionLookupRequest) -> OpenPositionLookupResponse: ...


class OpenPositionResolverPort(Protocol):
    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState: ...
