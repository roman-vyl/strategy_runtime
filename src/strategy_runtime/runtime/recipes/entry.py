"""Immutable singular desired-entry model returned by Strategy Engine."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from strategy_runtime.shared.decimal_text import normalize_decimal_text


@dataclass(frozen=True, slots=True)
class DesiredEntry:
    side: Literal["long", "short"]
    source_plan_bar_open_time_ms: int
    planned_entry_price: str
    initial_stop_price: str
    initial_take_price: str
    locked_exit_profile: str

    def __post_init__(self) -> None:
        if self.side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        if self.source_plan_bar_open_time_ms < 0:
            raise ValueError("source_plan_bar_open_time_ms must be non-negative")
        object.__setattr__(
            self, "planned_entry_price", normalize_decimal_text(self.planned_entry_price)
        )
        object.__setattr__(
            self, "initial_stop_price", normalize_decimal_text(self.initial_stop_price)
        )
        initial_take_price = normalize_decimal_text(self.initial_take_price)
        if Decimal(initial_take_price) <= 0:
            raise ValueError("initial_take_price must be positive")
        object.__setattr__(self, "initial_take_price", initial_take_price)
        if not self.locked_exit_profile.strip():
            raise ValueError("locked_exit_profile must be non-empty")
