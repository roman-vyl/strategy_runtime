"""Errors for position-management execution: domain invariants and ABI client outcomes."""

from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue


class PositionManagementExecutionInvariantError(RuntimeError):
    """A command or confirmation contradicts the expected position-management transition."""


class PositionManagementExecutionError(RuntimeError):
    """Base class for an ABI position-management call that returns no confirmation."""

    code = "position_management_execution_error"


class PositionManagementExecutionUnavailable(PositionManagementExecutionError):
    """ABI was unavailable: a transport failure or `internal_error` prevented a confirmation."""

    code = "position_management_execution_unavailable"


class PositionManagementExecutionTimeout(PositionManagementExecutionUnavailable):
    """The single bounded ABI HTTP attempt timed out."""

    code = "position_management_execution_timeout"


class PositionManagementExecutionNetworkFailure(PositionManagementExecutionUnavailable):
    """A non-timeout network transport failure prevented a valid ABI response."""

    code = "position_management_execution_network_failure"


class PositionManagementExecutionProtocolError(PositionManagementExecutionError):
    """ABI returned a response outside the approved public HTTP contract."""

    code = "position_management_execution_protocol_error"


class PositionManagementExecutionPublicError(PositionManagementExecutionError):
    """A documented ABI 400/415/422 position-management business rejection."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: FrozenJsonValue | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
