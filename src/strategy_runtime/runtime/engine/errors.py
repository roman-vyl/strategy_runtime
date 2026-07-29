"""Strategy Engine projection failure taxonomy, transport-independent."""

from collections.abc import Mapping

from strategy_runtime.runtime.routing.errors import (
    StrategyEngineProjectionUnavailable as _RoutedStrategyEngineProjectionUnavailable,
)
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue


class StrategyEngineProjectionError(RuntimeError):
    """Base class for every Strategy Engine projection failure."""

    code = "strategy_engine_projection_error"


class StrategyEngineProjectionUnavailable(
    StrategyEngineProjectionError, _RoutedStrategyEngineProjectionUnavailable
):
    """Superclass of every Engine HTTP-failure branch.

    Also inherits `routing.errors.StrategyEngineProjectionUnavailable` so every
    branch remains compatible with the canonical `use-case-router` contract,
    which already observes Engine HTTP failures under that existing type.
    """

    code = "strategy_engine_projection_unavailable"


class StrategyEngineProjectionPublicError(StrategyEngineProjectionUnavailable):
    """A documented non-2xx Engine business rejection."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, FrozenJsonValue],
        request_id: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.request_id = request_id


class StrategyEngineMarketStreamNotFound(StrategyEngineProjectionPublicError):
    """HTTP 404 with error code `market_stream_not_found`."""


class StrategyEngineProjectionTimeout(StrategyEngineProjectionUnavailable):
    """The single bounded Engine HTTP attempt timed out."""

    code = "strategy_engine_projection_timeout"


class StrategyEngineProjectionNetworkFailure(StrategyEngineProjectionUnavailable):
    """A non-timeout network transport failure prevented a valid Engine response."""

    code = "strategy_engine_projection_network_failure"


class StrategyEngineProjectionProtocolError(StrategyEngineProjectionUnavailable):
    """Engine returned a response outside the approved public HTTP contract."""

    code = "strategy_engine_projection_protocol_error"
