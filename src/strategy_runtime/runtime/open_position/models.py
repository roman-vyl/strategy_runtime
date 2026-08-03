"""Open-position lookup and transient resolved-state models."""

from dataclasses import dataclass

from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.shared.decimal_text import (
    is_positive_exact_decimal_text,
    normalize_decimal_text,
)


@dataclass(frozen=True, slots=True)
class OpenPositionLookupRequest:
    strategy_instance_id: str
    trade_cycle_id: str

    def __post_init__(self) -> None:
        if not self.strategy_instance_id.strip():
            raise ValueError("strategy_instance_id must be non-empty")
        if not self.trade_cycle_id.strip():
            raise ValueError("trade_cycle_id must be non-empty")


@dataclass(frozen=True, slots=True)
class OpenPositionLookupResponse:
    position_open: bool
    first_fill_at_ms: int | None = None
    average_entry_price: str | None = None

    def __post_init__(self) -> None:
        if type(self.position_open) is not bool:
            raise TypeError("position_open must be a boolean")
        if self.position_open:
            if self.first_fill_at_ms is None or self.average_entry_price is None:
                raise ValueError("open position requires first fill time and average entry price")
            if self.first_fill_at_ms <= 0:
                raise ValueError("first_fill_at_ms must be strictly positive")
            if not is_positive_exact_decimal_text(self.average_entry_price):
                raise ValueError("average_entry_price must be positive exact-decimal text")
            object.__setattr__(
                self, "average_entry_price", normalize_decimal_text(self.average_entry_price)
            )
        elif self.first_fill_at_ms is not None or self.average_entry_price is not None:
            raise ValueError("closed position cannot contain fill facts")


@dataclass(frozen=True, slots=True)
class PositionResolvedStrategyInstanceRuntimeState:
    runtime_state: StrategyInstanceRuntimeState
    position_open: bool
    first_fill_at_ms: int | None
    average_entry_price: str | None

    @property
    def strategy_instance_id(self) -> str:
        return self.runtime_state.strategy_instance_id
