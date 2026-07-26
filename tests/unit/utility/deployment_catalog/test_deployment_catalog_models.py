from types import MappingProxyType

import pytest

from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentSpecification,
)


def deployment(strategy_instance_id: str = "one") -> DeploymentSpecification:
    return DeploymentSpecification(
        strategy_instance_id=strategy_instance_id,
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="ema_pullback",
        raw_spec={"components": {"nested": [1, {"value": 2}]}},
        source_path=f"{strategy_instance_id}.json",
    )


def test_deployment_is_deeply_immutable_and_detached() -> None:
    source = {"components": {"nested": [1, {"value": 2}]}}
    item = DeploymentSpecification(
        strategy_instance_id="one",
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="ema_pullback",
        raw_spec=source,
        source_path="one.json",
    )

    source["components"]["nested"][1]["value"] = 99  # type: ignore[index]
    source["components"]["nested"].append(3)  # type: ignore[union-attr]

    assert isinstance(item.raw_spec, MappingProxyType)
    components = item.raw_spec["components"]
    assert isinstance(components, MappingProxyType)
    assert components["nested"] == (1, MappingProxyType({"value": 2}))

    with pytest.raises(TypeError):
        item.raw_spec["x"] = 2  # type: ignore[index]

    assert not hasattr(item, "risk_multiplier")


def test_snapshot_supports_identity_lookup_only() -> None:
    items = (deployment("a"), deployment("b"))
    snapshot = DeploymentCatalogSnapshot(2, items, (), ())

    assert snapshot.get_by_strategy_instance_id("b") is items[1]
    assert snapshot.get_by_strategy_instance_id("missing") is None
    assert not hasattr(snapshot, "find_for_stream")


def test_snapshot_rejects_duplicate_accepted_identity() -> None:
    with pytest.raises(ValueError, match="unique stable identities"):
        DeploymentCatalogSnapshot(2, (deployment("same"), deployment("same")), (), ())
