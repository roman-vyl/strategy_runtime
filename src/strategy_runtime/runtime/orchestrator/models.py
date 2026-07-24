"""Input and output models for semantic Runtime orchestration."""

from dataclasses import dataclass

from strategy_runtime.runtime.routing.models import StrategyUseCaseProjectedInstance


@dataclass(frozen=True, slots=True)
class StrategyRuntimeProjectionResult:
    strategy_instance_id: str
    projection: StrategyUseCaseProjectedInstance
