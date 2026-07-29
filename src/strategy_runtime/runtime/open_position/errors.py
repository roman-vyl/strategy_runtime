"""Typed open-position resolution failures."""

from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue


class OpenPositionResolutionError(RuntimeError):
    code = "open_position_resolution_error"


class OpenPositionLookupUnavailable(OpenPositionResolutionError):
    code = "open_position_lookup_unavailable"


class OpenPositionLookupTimeout(OpenPositionLookupUnavailable):
    """The single bounded ABI open-position HTTP attempt timed out."""

    code = "open_position_lookup_timeout"


class OpenPositionLookupNetworkFailure(OpenPositionLookupUnavailable):
    """A non-timeout network transport failure prevented a valid ABI response."""

    code = "open_position_lookup_network_failure"


class OpenPositionLookupProtocolError(OpenPositionResolutionError):
    code = "open_position_lookup_protocol_error"


class OpenPositionLookupPublicError(OpenPositionResolutionError):
    """A documented ABI 400/422 open-position business rejection."""

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
