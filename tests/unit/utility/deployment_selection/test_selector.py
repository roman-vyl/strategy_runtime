from dataclasses import FrozenInstanceError

import pytest

from strategy_runtime.utility.committed_bar.models import CommittedBarEvent
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentSpecification,
)
from strategy_runtime.utility.deployment_selection import CommittedBarDeploymentSelector


def deployment(
    identity: str,
    *,
    enabled: bool = True,
    instrument: str = "BTCUSDT.P",
    timeframe: str = "5m",
) -> DeploymentSpecification:
    return DeploymentSpecification(
        strategy_instance_id=identity,
        enabled=enabled,
        instrument=instrument,
        base_timeframe=timeframe,
        strategy_id="ema_pullback",
        raw_spec={"identity": identity},
        source_path=f"{identity}.json",
    )


def snapshot(*deployments: DeploymentSpecification) -> DeploymentCatalogSnapshot:
    return DeploymentCatalogSnapshot(len(deployments), deployments, (), ())


def event(instrument: str = "BTCUSDT.P", timeframe: str = "5m") -> CommittedBarEvent:
    return CommittedBarEvent(instrument, timeframe, 123)


def test_selects_only_exact_enabled_stream_matches() -> None:
    catalog = snapshot(
        deployment("selected"),
        deployment("disabled", enabled=False),
        deployment("other-instrument", instrument="ETHUSDT.P"),
        deployment("other-timeframe", timeframe="1h"),
    )
    result = CommittedBarDeploymentSelector().select(event=event(), snapshot=catalog)
    assert tuple(item.strategy_instance_id for item in result) == ("selected",)


def test_matching_is_case_sensitive() -> None:
    catalog = snapshot(deployment("upper"), deployment("lower", instrument="btcusdt.p"))
    result = CommittedBarDeploymentSelector().select(event=event(), snapshot=catalog)
    assert tuple(item.strategy_instance_id for item in result) == ("upper",)


def test_empty_catalog_returns_empty_tuple() -> None:
    assert CommittedBarDeploymentSelector().select(event=event(), snapshot=snapshot()) == ()


def test_results_are_immutable_and_repeatable() -> None:
    selector = CommittedBarDeploymentSelector()
    catalog = snapshot(deployment("a"))
    first = selector.select(event=event(), snapshot=catalog)
    second = selector.select(event=event(), snapshot=catalog)
    assert first == second
    with pytest.raises(FrozenInstanceError):
        first[0].strategy_instance_id = "changed"  # type: ignore[misc]
