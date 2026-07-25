"""Open-trade Strategy Engine transport models and port."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue


@dataclass(frozen=True, slots=True)
class OpenTradeProjectionRequest:
    strategy_id: str
    raw_spec: Mapping[str, FrozenJsonValue]
    ticker: str
    base_timeframe: str
    target_bar_open_time_ms: int
    desired_entry: DesiredEntry
    entry_bar_open_time_ms: int


@dataclass(frozen=True, slots=True)
class OpenTradeProjectionResponse:
    desired_protection: DesiredProtection
    close_signal: CloseSignal
    diagnostics: Mapping[str, FrozenJsonValue]


class StrategyEngineOpenTradePort(Protocol):
    def project_open_trade(
        self, request: OpenTradeProjectionRequest
    ) -> OpenTradeProjectionResponse: ...
