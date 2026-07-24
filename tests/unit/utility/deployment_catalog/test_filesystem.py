import json
from pathlib import Path

import pytest

from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogUnavailableError,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)


def spec_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": True,
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "strategy_id": "ema_pullback",
        "raw_spec": {"anything": [1, 2, 3]},
        "future": "allowed",
    }
    payload.update(overrides)
    return payload


def write_spec(path: Path, **overrides: object) -> None:
    path.write_text(json.dumps(spec_payload(**overrides)), encoding="utf-8")


def expected_id(**overrides: object) -> str:
    payload = spec_payload(**overrides)
    return derive_strategy_instance_id(
        strategy_id=payload["strategy_id"],  # type: ignore[arg-type]
        ticker=payload["ticker"],  # type: ignore[arg-type]
        base_timeframe=payload["base_timeframe"],  # type: ignore[arg-type]
        raw_spec=payload["raw_spec"],  # type: ignore[arg-type]
    )


def test_discovers_direct_visible_json_in_deterministic_order(tmp_path: Path) -> None:
    write_spec(tmp_path / "b.json", ticker="ETHUSDT.P")
    write_spec(tmp_path / "a.json")
    write_spec(tmp_path / ".hidden.json", ticker="SOLUSDT.P")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    write_spec(nested / "nested.json", ticker="XRPUSDT.P")

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert snapshot.scanned_file_count == 2
    assert [item.source_path for item in snapshot.accepted_deployments] == [
        "a.json",
        "b.json",
    ]
    assert [item.strategy_instance_id for item in snapshot.accepted_deployments] == [
        expected_id(),
        expected_id(ticker="ETHUSDT.P"),
    ]


def test_invalid_files_are_isolated_and_duplicates_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    write_spec(tmp_path / "a.json")
    write_spec(tmp_path / "b.json")
    write_spec(tmp_path / "ok.json", ticker="ETHUSDT.P")

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert [item.strategy_instance_id for item in snapshot.accepted_deployments] == [
        expected_id(ticker="ETHUSDT.P")
    ]
    assert snapshot.invalid_files[0].error_code == "invalid_json"
    assert snapshot.duplicate_identities[0].strategy_instance_id == expected_id()
    assert snapshot.duplicate_identities[0].source_paths == ("a.json", "b.json")


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_number_is_rejected_without_aborting_catalog(
    tmp_path: Path,
    literal: str,
) -> None:
    (tmp_path / "bad.json").write_text(
        (
            '{"enabled":true,"ticker":"BTCUSDT.P","base_timeframe":"5m",'
            f'"strategy_id":"bad","raw_spec":{{"value":{literal}}}}}'
        ),
        encoding="utf-8",
    )
    write_spec(tmp_path / "valid.json", strategy_id="valid")

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert [item.strategy_id for item in snapshot.accepted_deployments] == ["valid"]
    assert len(snapshot.invalid_files) == 1
    assert snapshot.invalid_files[0].source_path == "bad.json"
    assert snapshot.invalid_files[0].error_code == "invalid_json"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"ticker": ""}, "empty_required_field"),
        ({"ticker": 1}, "invalid_field_type"),
        ({"raw_spec": []}, "invalid_raw_spec"),
    ],
)
def test_required_field_validation(tmp_path: Path, overrides: dict[str, object], code: str) -> None:
    write_spec(tmp_path / "bad.json", **overrides)

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert snapshot.invalid_files[0].error_code == code


@pytest.mark.parametrize(
    "field_name",
    ["enabled", "ticker", "base_timeframe", "strategy_id", "raw_spec"],
)
def test_every_required_field_is_rejected_when_missing(
    tmp_path: Path,
    field_name: str,
) -> None:
    payload = spec_payload()
    del payload[field_name]
    (tmp_path / "bad.json").write_text(json.dumps(payload), encoding="utf-8")

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert snapshot.accepted_deployments == ()
    assert snapshot.invalid_files[0].error_code == "missing_required_field"
    assert snapshot.invalid_files[0].error_message == field_name


def test_identity_is_stable_across_filename_and_json_key_order(tmp_path: Path) -> None:
    first = spec_payload()
    second = {
        "raw_spec": {"anything": [1, 2, 3]},
        "strategy_id": "ema_pullback",
        "base_timeframe": "5m",
        "ticker": "BTCUSDT.P",
        "enabled": False,
        "future": "different non-semantic metadata",
    }
    (tmp_path / "z.json").write_text(json.dumps(first, indent=2), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps(second), encoding="utf-8")

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert snapshot.accepted_deployments == ()
    assert len(snapshot.duplicate_identities) == 1
    assert snapshot.duplicate_identities[0].strategy_instance_id == expected_id()


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticker": "ETHUSDT.P"},
        {"base_timeframe": "15m"},
        {"strategy_id": "other_strategy"},
        {"raw_spec": {"anything": [1, 2, 4]}},
    ],
)
def test_semantic_or_market_change_creates_new_identity(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    write_spec(tmp_path / "base.json")
    write_spec(tmp_path / "changed.json", **overrides)

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert len(snapshot.accepted_deployments) == 2
    assert len({item.strategy_instance_id for item in snapshot.accepted_deployments}) == 2
    assert snapshot.duplicate_identities == ()


@pytest.mark.parametrize(
    "field_name",
    ["strategy_instance_id", "strategy_version", "compatibility_profile"],
)
def test_obsolete_identity_fields_are_rejected(tmp_path: Path, field_name: str) -> None:
    write_spec(tmp_path / "bad.json", **{field_name: "obsolete"})

    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert snapshot.accepted_deployments == ()
    assert snapshot.invalid_files[0].error_code == "forbidden_obsolete_field"
    assert snapshot.invalid_files[0].error_message == field_name


def test_empty_catalog_is_valid(tmp_path: Path) -> None:
    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()

    assert snapshot.scanned_file_count == 0
    assert snapshot.accepted_deployments == ()
    assert snapshot.invalid_files == ()
    assert snapshot.duplicate_identities == ()


def test_missing_catalog_directory_is_catalog_level_failure(tmp_path: Path) -> None:
    with pytest.raises(DeploymentCatalogUnavailableError):
        FilesystemDeploymentCatalog(tmp_path / "missing").load_snapshot()


def test_enabled_is_required_boolean_and_does_not_affect_identity(tmp_path: Path) -> None:
    write_spec(tmp_path / "enabled.json", enabled=True)
    write_spec(tmp_path / "disabled.json", enabled=False)
    snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()
    assert snapshot.accepted_deployments == ()
    assert len(snapshot.duplicate_identities) == 1

    other = tmp_path / "bad"
    other.mkdir()
    write_spec(other / "bad.json", enabled="yes")
    invalid = FilesystemDeploymentCatalog(other).load_snapshot()
    assert invalid.invalid_files[0].error_code == "invalid_field_type"
    assert invalid.invalid_files[0].error_message == "enabled"
