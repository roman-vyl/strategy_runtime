"""Open-position lookup and transient resolved-state models."""

from dataclasses import dataclass

from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
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
    closure: TradeCycleClosure | None = None
    # The cycle's own entry order whose fill ABI proved
    # (runtime-trade-cycle-opened-v1 D2). Transient, never persisted.
    entry_order_link_id: str | None = None
    entry_order_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.position_open) is not bool:
            raise TypeError("position_open must be a boolean")
        if self.closure is not None and type(self.closure) is not TradeCycleClosure:
            raise TypeError("closure must be TradeCycleClosure or None")
        if self.position_open:
            if self.closure is not None:
                raise ValueError("open position cannot carry a closure")
            if self.first_fill_at_ms is None or self.average_entry_price is None:
                raise ValueError("open position requires first fill time and average entry price")
            if self.first_fill_at_ms <= 0:
                raise ValueError("first_fill_at_ms must be strictly positive")
            if not is_positive_exact_decimal_text(self.average_entry_price):
                raise ValueError("average_entry_price must be positive exact-decimal text")
            _validate_open_entry_order_identity(self.entry_order_link_id, self.entry_order_id)
            object.__setattr__(
                self, "average_entry_price", normalize_decimal_text(self.average_entry_price)
            )
        else:
            if self.first_fill_at_ms is not None or self.average_entry_price is not None:
                raise ValueError("closed position cannot contain fill facts")
            if self.entry_order_link_id is not None or self.entry_order_id is not None:
                raise ValueError("closed position cannot identify an entry order")


@dataclass(frozen=True, slots=True)
class PositionResolvedStrategyInstanceRuntimeState:
    runtime_state: StrategyInstanceRuntimeState
    position_open: bool
    first_fill_at_ms: int | None
    average_entry_price: str | None
    closure: TradeCycleClosure | None = None
    entry_order_link_id: str | None = None
    entry_order_id: str | None = None

    @property
    def strategy_instance_id(self) -> str:
        return self.runtime_state.strategy_instance_id


def _validate_open_entry_order_identity(link_id: object, order_id: object) -> None:
    """An open position names its entry order; the exchange id may be absent."""
    if type(link_id) is not str or len(link_id) == 0:
        raise ValueError("open position requires a non-empty entry_order_link_id")
    if order_id is not None and (type(order_id) is not str or len(order_id) == 0):
        raise ValueError("entry_order_id must be a non-empty string or null")
