"""Long-lived strategy-instance and trade-cycle state models."""

from collections.abc import Mapping
from dataclasses import dataclass

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.shared.decimal_text import (
    is_exact_decimal_text,
    is_positive_exact_decimal_text,
)
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
class AppliedEntryPackage:
    applied_desired_entry: DesiredEntry
    calculated_quantity: str

    def __post_init__(self) -> None:
        if type(self.applied_desired_entry) is not DesiredEntry:
            raise TypeError("applied_desired_entry must be DesiredEntry")
        if not is_exact_decimal_text(self.calculated_quantity):
            raise ValueError("calculated_quantity must be exact-decimal text")


@dataclass(frozen=True, slots=True)
class CurrentTradeCycle:
    trade_cycle_id: str
    applied_entry_package: AppliedEntryPackage

    def __post_init__(self) -> None:
        if type(self.trade_cycle_id) is not str or len(self.trade_cycle_id) == 0:
            raise ValueError("trade_cycle_id must be a non-empty string")
        if type(self.applied_entry_package) is not AppliedEntryPackage:
            raise TypeError("applied_entry_package must be AppliedEntryPackage")

    @property
    def desired_entry_frozen(self) -> bool:
        """Compatibility read for the unchanged pre-I2 router; not persisted state."""
        return True

    @property
    def desired_entry(self) -> DesiredEntry:
        """Read the singular applied entry without duplicating it on the cycle."""
        return self.applied_entry_package.applied_desired_entry


@dataclass(frozen=True, slots=True)
class StrategyInstanceRuntimeState:
    strategy_instance_id: str
    strategy_id: str
    registered_spec_snapshot: RegisteredSpecSnapshot
    risk_multiplier: str
    current_trade_cycle: CurrentTradeCycle | None = None

    def __post_init__(self) -> None:
        if not self.strategy_instance_id.strip() or not self.strategy_id.strip():
            raise ValueError("strategy identity fields must be non-empty")
        if not is_positive_exact_decimal_text(self.risk_multiplier):
            raise ValueError("risk_multiplier must be positive exact-decimal text")
        if (
            self.current_trade_cycle is not None
            and type(self.current_trade_cycle) is not CurrentTradeCycle
        ):
            raise TypeError("current_trade_cycle must be CurrentTradeCycle or None")


@dataclass(frozen=True, slots=True)
class GetOrCreateStrategyInstanceRuntimeStateRequest:
    strategy_instance_id: str
    strategy_id: str
    instrument: str
    base_timeframe: str
    raw_spec: Mapping[str, FrozenJsonValue]
    source_path: str
