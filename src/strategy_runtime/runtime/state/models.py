"""Long-lived strategy-instance and trade-cycle state models."""

from collections.abc import Mapping
from dataclasses import dataclass

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import PositionManagementRecipe
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue, freeze_json


@dataclass(frozen=True, slots=True)
class RegisteredSpecSnapshot:
    instrument: str
    base_timeframe: str
    raw_spec: Mapping[str, FrozenJsonValue]
    source_path: str

    def __post_init__(self) -> None:
        for name in ("instrument", "base_timeframe", "source_path"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        frozen = freeze_json(dict(self.raw_spec))
        if not isinstance(frozen, Mapping):
            raise TypeError("raw_spec must be an object")
        object.__setattr__(self, "raw_spec", frozen)


@dataclass(frozen=True, slots=True)
class CurrentTradeCycle:
    trade_cycle_id: str
    desired_entry: DesiredEntry
    desired_entry_frozen: bool
    position_management_recipe: PositionManagementRecipe | None = None

    def __post_init__(self) -> None:
        if not self.trade_cycle_id.strip():
            raise ValueError("trade_cycle_id must be non-empty")


@dataclass(frozen=True, slots=True)
class StrategyInstanceRuntimeState:
    strategy_instance_id: str
    strategy_id: str
    registered_spec_snapshot: RegisteredSpecSnapshot
    current_trade_cycle: CurrentTradeCycle | None = None

    def __post_init__(self) -> None:
        if not self.strategy_instance_id.strip() or not self.strategy_id.strip():
            raise ValueError("strategy identity fields must be non-empty")


@dataclass(frozen=True, slots=True)
class GetOrCreateStrategyInstanceRuntimeStateRequest:
    strategy_instance_id: str
    strategy_id: str
    instrument: str
    base_timeframe: str
    raw_spec: Mapping[str, FrozenJsonValue]
    source_path: str
