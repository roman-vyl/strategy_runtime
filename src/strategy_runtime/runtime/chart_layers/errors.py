"""Refusals of a chart-layers request; `status_code` and `reason` are the HTTP answer."""

from strategy_runtime.runtime.enabled_control.errors import (
    CatalogUnavailable,
    EnabledControlRefused,
    StrategyInstanceNotFound,
)

__all__ = [
    "CatalogUnavailable",
    "ChartLayersRefused",
    "EngineRejected",
    "EngineUnavailable",
    "StrategyInstanceNotFound",
]

# The catalog refusals are shared with the enabled change and the delete; the route maps every
# `EnabledControlRefused` the same way, so the chart-layers ones derive from the same base.
ChartLayersRefused = EnabledControlRefused


class EngineUnavailable(EnabledControlRefused):
    status_code = 502
    reason = "engine_unavailable"


class EngineRejected(EnabledControlRefused):
    status_code = 422
    reason = "engine_rejected"

    def __init__(self, *, engine_code: str, engine_message: str) -> None:
        super().__init__()
        self.engine_code = engine_code
        self.engine_message = engine_message
