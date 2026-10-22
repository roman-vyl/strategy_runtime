"""Result of a successful enabled change."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnabledChangeResult:
    strategy_instance_id: str
    enabled: bool
    cancelled_entry_order: bool
