"""Typed open-position resolution failures."""


class OpenPositionResolutionError(RuntimeError):
    code = "open_position_resolution_error"


class OpenPositionLookupUnavailable(OpenPositionResolutionError):
    code = "open_position_lookup_unavailable"


class OpenPositionLookupProtocolError(OpenPositionResolutionError):
    code = "open_position_lookup_protocol_error"
