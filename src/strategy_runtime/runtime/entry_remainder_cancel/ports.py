"""Ports for cancelling the unfilled remainder of a filled touch_trigger entry order."""

from typing import Protocol

from strategy_runtime.runtime.position_management_execution.models import (
    EntryRemainderCancelConfirmation,
)


class EntryRemainderCancelPort(Protocol):
    """Ask ABI to end the cycle's entry-order remainder; ABI finds the order itself.

    Returns a confirmation only once ABI confirmed the entry order terminal; any other
    outcome raises.
    """

    def cancel_entry_remainder(
        self, strategy_instance_id: str, trade_cycle_id: str
    ) -> EntryRemainderCancelConfirmation: ...


class EntryRemainderCancelJournalPort(Protocol):
    """Record each entry-remainder cancel outcome. Best effort; must not raise."""

    def entry_remainder_cancelled(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int,
        status: str,
        executed_quantity: str | None,
    ) -> None: ...

    def entry_remainder_cancel_failed(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int,
        error: str,
    ) -> None: ...
