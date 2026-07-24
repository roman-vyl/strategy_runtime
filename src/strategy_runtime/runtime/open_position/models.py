"""Open-position lookup and transient resolved-state models."""

from dataclasses import dataclass

from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.shared.decimal_text import normalize_decimal_text


@dataclass(frozen=True, slots=True)
class OpenPositionLookupRequest:
    strategy_instance_id: str

    def __post_init__(self) -> None:
        if not self.strategy_instance_id.strip():
            raise ValueError("strategy_instance_id must be non-empty")


@dataclass(frozen=True, slots=True)
class OpenPositionLookupResponse:
    position_open: bool
    entry_bar_open_time_ms: int | None = None
    executed_entry_price: str | None = None

    def __post_init__(self) -> None:
        if type(self.position_open) is not bool:
            raise TypeError("position_open must be a boolean")
        if self.position_open:
            if self.entry_bar_open_time_ms is None or self.executed_entry_price is None:
                raise ValueError("open position requires entry bar and executed price")
            if self.entry_bar_open_time_ms < 0:
                raise ValueError("entry_bar_open_time_ms must be non-negative")
            object.__setattr__(
                self, "executed_entry_price", normalize_decimal_text(self.executed_entry_price)
            )
        elif self.entry_bar_open_time_ms is not None or self.executed_entry_price is not None:
            raise ValueError("closed position cannot contain entry facts")


@dataclass(frozen=True, slots=True)
class PositionResolvedStrategyInstanceRuntimeState:
    runtime_state: StrategyInstanceRuntimeState
    position_open: bool
    entry_bar_open_time_ms: int | None
    executed_entry_price: str | None

    @property
    def strategy_instance_id(self) -> str:
        return self.runtime_state.strategy_instance_id
