"""Live-entry Strategy Engine transport models and port."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from strategy_runtime.runtime.recipes.entry import LiveEntryPlan
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue


@dataclass(frozen=True, slots=True)
class LiveEntryProjectionRequest:
    strategy_id: str
    raw_spec: Mapping[str, FrozenJsonValue]
    ticker: str
    base_timeframe: str
    target_bar_open_time_ms: int


@dataclass(frozen=True, slots=True)
class LiveEntryProjectionResponse:
    plans_by_side: Mapping[str, LiveEntryPlan | None]


class StrategyEngineLiveEntryPort(Protocol):
    def project_live_entry(
        self, request: LiveEntryProjectionRequest
    ) -> LiveEntryProjectionResponse: ...
