"""Application-level input for AbiExecutionEventOrchestrator."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AbiFirstFillExecutionEvent:
    strategy_instance_id: str
    trade_cycle_id: str
    first_fill_at_ms: int

    def __post_init__(self) -> None:
        if type(self.strategy_instance_id) is not str or len(self.strategy_instance_id) == 0:
            raise ValueError("strategy_instance_id must be a non-empty string")
        if type(self.trade_cycle_id) is not str or len(self.trade_cycle_id) == 0:
            raise ValueError("trade_cycle_id must be a non-empty string")
        if type(self.first_fill_at_ms) is not int or self.first_fill_at_ms <= 0:
            raise ValueError("first_fill_at_ms must be a strictly positive integer")
