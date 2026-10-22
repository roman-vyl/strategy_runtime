"""Result of a successful delete."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeleteResult:
    strategy_instance_id: str
    cancelled_entry_order: bool
    trash_file: str
