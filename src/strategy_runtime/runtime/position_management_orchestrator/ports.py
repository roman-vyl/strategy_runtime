"""External execution boundary for position-management execution."""

from collections.abc import Mapping
from typing import Protocol

from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.utility.processing_journal.models import JsonValue


class PositionManagementExecutionPort(Protocol):
    """Execute one position-management command, returning a verified confirmation.

    `apply_protection` SHALL return `ProtectionAppliedConfirmation` only once the
    requested protection is verified applied. `close_position` SHALL return
    `PositionClosedConfirmation` only once no open position remainder is
    verified to exist. A response that only means the request was accepted,
    submitted, or queued is not a confirmation and SHALL NOT be returned.
    """

    def apply_protection(
        self,
        command: ApplyProtectionCommand,
    ) -> ProtectionAppliedConfirmation: ...

    def close_position(
        self,
        command: ClosePositionCommand,
    ) -> PositionClosedConfirmation: ...


class ProtectionAppliedJournalPort(Protocol):
    """Record one protection ABI confirmed, with the orders that carry it.

    Implementations are best effort and must not raise into orchestration.
    """

    def protection_applied(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int,
        requested_protection: Mapping[str, JsonValue],
        confirmed_protection: Mapping[str, JsonValue],
        position_quantity: str,
        stop_order: Mapping[str, JsonValue],
        take_order: Mapping[str, JsonValue],
    ) -> None: ...
