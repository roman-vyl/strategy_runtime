"""Use-case routing input and projected-result models."""

from dataclasses import dataclass

from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import PositionManagementRecipe
from strategy_runtime.utility.committed_bar.models import StrategyBarProcessingUnit
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification


@dataclass(frozen=True, slots=True)
class PositionResolvedStrategyInstance:
    processing_unit: StrategyBarProcessingUnit[DeploymentSpecification]
    resolved_state: PositionResolvedStrategyInstanceRuntimeState


@dataclass(frozen=True, slots=True)
class LiveEntryProjectedStrategyInstance:
    source: PositionResolvedStrategyInstance
    desired_entry: DesiredEntry | None


@dataclass(frozen=True, slots=True)
class OpenTradeProjectedStrategyInstance:
    source: PositionResolvedStrategyInstance
    position_management_recipe: PositionManagementRecipe


type StrategyUseCaseProjectedInstance = (
    LiveEntryProjectedStrategyInstance | OpenTradeProjectedStrategyInstance
)
