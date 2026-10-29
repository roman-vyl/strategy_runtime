"""Results of the operator commands."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClosePositionResult:
    strategy_instance_id: str
    trade_cycle_id: str
    enabled: bool
    closure_reason: str | None


@dataclass(frozen=True, slots=True)
class CancelEntryOrdersResult:
    strategy_instance_id: str
    enabled: bool
    cancelled_entry_order: bool
