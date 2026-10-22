"""Which EMA stack and episode parameters a strategy uses (`runtime-strategy-chart-layers-v1`).

Strategy Engine's feature plan is the single source: Runtime does not read the periods from the
specification and does not guess a role from the order of the planned features. Each role of the
stack is resolved through the plan's own mapping `anchor_columns` (role -> `output_id`) and the one
planned feature with that `output_id`.
"""

from collections.abc import Callable, Mapping
from typing import Protocol

from strategy_runtime.runtime.chart_layers.errors import (
    CatalogUnavailable,
    EngineRejected,
    EngineUnavailable,
    StrategyInstanceNotFound,
)
from strategy_runtime.runtime.chart_layers.models import ChartLayers, EmaStackEntry, EpisodeEntry
from strategy_runtime.runtime.engine.errors import (
    StrategyEngineProjectionPublicError,
    StrategyEngineProjectionUnavailable,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
)
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue

STACK_ROLES = ("fast", "anchor", "slow")
_ENGINE_REJECTION_STATUS = 422


class FeaturePlanPort(Protocol):
    def build_feature_plan(
        self, strategy_id: str, raw_spec: Mapping[str, FrozenJsonValue]
    ) -> Mapping[str, object]: ...


class StrategyChartLayersService:
    def __init__(
        self,
        *,
        load_snapshot: Callable[[], DeploymentCatalogSnapshot],
        feature_plan: FeaturePlanPort,
    ) -> None:
        self._load_snapshot = load_snapshot
        self._feature_plan = feature_plan

    def get(self, strategy_instance_id: str) -> ChartLayers:
        try:
            snapshot = self._load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise CatalogUnavailable from exc
        deployment = snapshot.get_by_strategy_instance_id(strategy_instance_id)
        if deployment is None:
            raise StrategyInstanceNotFound

        try:
            plan = self._feature_plan.build_feature_plan(
                deployment.strategy_id, deployment.raw_spec
            )
        except StrategyEngineProjectionPublicError as exc:
            if exc.status_code == _ENGINE_REJECTION_STATUS:
                raise EngineRejected(engine_code=exc.code, engine_message=exc.message) from exc
            raise EngineUnavailable from exc
        except StrategyEngineProjectionUnavailable as exc:
            raise EngineUnavailable from exc

        try:
            return ChartLayers(
                strategy_instance_id=strategy_instance_id,
                ema_stack=_ema_stack(plan),
                episodes=_episodes(plan),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineUnavailable from exc


def _ema_stack(plan: Mapping[str, object]) -> tuple[EmaStackEntry, ...]:
    anchor_columns = _mapping(plan["anchor_columns"], "anchor_columns")
    features = _sequence(plan["features"], "features")
    entries: list[EmaStackEntry] = []
    for role in STACK_ROLES:
        output_id = anchor_columns[role]
        if type(output_id) is not str:
            raise TypeError("anchor_columns value must be a string")
        matches = [
            feature
            for feature in features
            if isinstance(feature, Mapping) and feature.get("output_id") == output_id
        ]
        if len(matches) != 1:
            raise ValueError(f"no single planned feature for {output_id}")
        feature = matches[0]
        if feature.get("kind") != "ema":
            raise ValueError(f"planned feature {output_id} is not an EMA")
        parameters = _mapping(feature["parameters"], "parameters")
        period = parameters["period"]
        if type(period) is not int or period < 1:
            raise ValueError("period must be a positive integer")
        timeframe = feature["timeframe"]
        source = feature["source"]
        if type(timeframe) is not str or type(source) is not str:
            raise TypeError("timeframe and source must be strings")
        entries.append(EmaStackEntry(role, timeframe, period, source))
    return tuple(entries)


def _episodes(plan: Mapping[str, object]) -> tuple[EpisodeEntry, ...]:
    raw = plan.get("episode_params_by_ref")
    if raw is None:
        return ()
    by_ref = _mapping(raw, "episode_params_by_ref")
    entries: list[EpisodeEntry] = []
    for ref, params in by_ref.items():
        values = _mapping(params, "episode params")
        entries.append(EpisodeEntry(ref, dict(values)))  # type: ignore[arg-type]
    return tuple(entries)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value
