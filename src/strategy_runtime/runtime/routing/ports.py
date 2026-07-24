"""Use-case router port."""

from typing import Protocol

from strategy_runtime.runtime.routing.models import (
    PositionResolvedStrategyInstance,
    StrategyUseCaseProjectedInstance,
)


class StrategyUseCaseRouterPort(Protocol):
    def route(self, item: PositionResolvedStrategyInstance) -> StrategyUseCaseProjectedInstance: ...
