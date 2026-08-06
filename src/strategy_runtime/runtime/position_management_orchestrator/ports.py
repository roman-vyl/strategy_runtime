"""External execution boundary for position-management execution."""

from typing import Protocol

from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)


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
