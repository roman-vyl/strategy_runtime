"""Minimal output boundary owned by the utility orchestration contour."""

from collections.abc import Callable

from strategy_runtime.utility.committed_bar import (
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
)

type StrategyCycleHandoffSink[DeploymentT] = Callable[
    [StrategyBarProcessingUnit[DeploymentT]], None
]


class StrategyCycleHandoffBoundary[DeploymentT]:
    """Hand one prepared strategy/bar unit to a future downstream capability.

    The boundary deliberately performs no strategy-cycle, Engine, ABI, position,
    or trading work. A sink can be attached later without changing the utility
    orchestrator. With no sink attached, the boundary is an explicit terminal
    acceptance point for bootstrap and sandbox operation.
    """

    def __init__(
        self,
        sink: StrategyCycleHandoffSink[DeploymentT] | None = None,
    ) -> None:
        self._sink = sink

    def dispatch(
        self,
        unit: StrategyBarProcessingUnit[DeploymentT],
    ) -> StrategyCycleDispatchOutcome:
        if self._sink is not None:
            self._sink(unit)
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)
