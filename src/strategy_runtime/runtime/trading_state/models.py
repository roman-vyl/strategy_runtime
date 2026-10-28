"""Trade state of one strategy instance as Runtime itself stores it."""

from dataclasses import dataclass
from typing import Final, Literal

FLAT: Final = "flat"
ENTRY_PENDING: Final = "entry_pending"
IN_POSITION: Final = "in_position"

TradeState = Literal["flat", "entry_pending", "in_position"]
RecoveryPending = Literal["entry", "close"]


@dataclass(frozen=True, slots=True)
class StrategyInstanceTradingState:
    strategy_instance_id: str
    trade_state: TradeState
    trade_cycle_id: str | None
    side: Literal["long", "short"] | None
    first_fill_at_ms: int | None
    recovery_pending: RecoveryPending | None
