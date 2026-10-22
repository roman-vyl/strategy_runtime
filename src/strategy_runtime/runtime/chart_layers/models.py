"""Answer of a chart-layers request."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmaStackEntry:
    role: str
    timeframe: str
    period: int
    source: str


@dataclass(frozen=True, slots=True)
class EpisodeEntry:
    episode_ref: str
    params: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ChartLayers:
    strategy_instance_id: str
    ema_stack: tuple[EmaStackEntry, ...]
    episodes: tuple[EpisodeEntry, ...]
