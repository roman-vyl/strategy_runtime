"""Transient value of a trade-cycle completion proven by ABI; never persisted."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_runtime.runtime.trade_cycle_closure.ports import TradeCycleClosedJournalPort

STOP_LOSS = "stop_loss"
TAKE_PROFIT = "take_profit"
RUNTIME_SIGNAL = "runtime_signal"
TRADE_CYCLE_CLOSURE_REASONS = frozenset({STOP_LOSS, TAKE_PROFIT, RUNTIME_SIGNAL})


@dataclass(frozen=True, slots=True)
class TradeCycleClosure:
    strategy_instance_id: str
    trade_cycle_id: str
    reason: str
    order_id: str
    order_link_id: str | None
    parent_order_link_id: str | None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_non_empty_string(self.order_id, "order_id")
        if self.reason not in TRADE_CYCLE_CLOSURE_REASONS:
            raise ValueError(f"unsupported closure reason: {self.reason!r}")
        if self.reason == RUNTIME_SIGNAL:
            _require_non_empty_string(self.order_link_id, "order_link_id")
            if self.parent_order_link_id is not None:
                raise ValueError("runtime_signal closure must not carry parent_order_link_id")
        else:
            _require_non_empty_string(self.parent_order_link_id, "parent_order_link_id")
            if self.order_link_id is not None:
                raise ValueError("protection closure must not carry order_link_id")


def _require_non_empty_string(value: object, name: str) -> None:
    if type(value) is not str or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty string")


def journal_trade_cycle_closed(
    journal: "TradeCycleClosedJournalPort | None",
    closure: TradeCycleClosure,
    bar_open_time_ms: int | None,
) -> None:
    """Write one `trade_cycle_closed` record; call only after the durable save."""
    if journal is None:
        return
    journal.trade_cycle_closed(
        strategy_instance_id=closure.strategy_instance_id,
        trade_cycle_id=closure.trade_cycle_id,
        bar_open_time_ms=bar_open_time_ms,
        reason=closure.reason,
        order_id=closure.order_id,
        order_link_id=closure.order_link_id,
        parent_order_link_id=closure.parent_order_link_id,
    )
