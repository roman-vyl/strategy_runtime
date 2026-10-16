"""HTTP integration tests for GET /v1/strategy-instances (read-only catalog listing)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

PATH = "/v1/strategy-instances"
ITEM_FIELDS = {
    "strategy_instance_id",
    "strategy_id",
    "instrument",
    "base_timeframe",
    "enabled",
    "source_path",
}


class RecordingLogger:
    def __init__(self) -> None:
        self.exception_calls: list[str] = []

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self.exception_calls.append(message)

    def error(self, message: str, **kwargs: object) -> None: ...

    def warning(self, message: str, **kwargs: object) -> None: ...


def write_spec(
    directory: Path,
    name: str,
    *,
    enabled: bool = True,
    ticker: str = "ETHUSDT.P",
    raw_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = {
        "enabled": enabled,
        "ticker": ticker,
        "base_timeframe": "5m",
        "strategy_id": "ema_pullback",
        "raw_spec": raw_spec if raw_spec is not None else {"anchor": 500, "secret": "x"},
    }
    (directory / name).write_text(json.dumps(document), encoding="utf-8")
    return document


def make_client(
    loader: Any,
    *,
    ready: bool = True,
    logger: RecordingLogger | None = None,
) -> TestClient:
    app = create_http_app(
        ready=ready,
        committed_bar_intake=None,
        process_first_fill=None,
        load_deployment_catalog=loader,
        logger=logger or RecordingLogger(),  # type: ignore[arg-type]
    )
    return TestClient(app)


def catalog_client(directory: Path) -> TestClient:
    return make_client(FilesystemDeploymentCatalog(directory).load_snapshot)


def test_lists_enabled_and_disabled_in_file_name_order(tmp_path: Path) -> None:
    write_spec(tmp_path, "b.json", enabled=False, raw_spec={"anchor": 200})
    write_spec(tmp_path, "a.json", enabled=True, raw_spec={"anchor": 500})

    response = catalog_client(tmp_path).get(PATH)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "scanned_file_count",
        "strategy_instances",
        "invalid_files",
        "duplicate_identities",
    }
    assert body["scanned_file_count"] == 2
    items = body["strategy_instances"]
    assert [item["source_path"] for item in items] == ["a.json", "b.json"]
    assert [item["enabled"] for item in items] == [True, False]
    for item in items:
        assert set(item) == ITEM_FIELDS
        assert item["strategy_id"] == "ema_pullback"
        assert item["instrument"] == "ETHUSDT.P"
        assert item["base_timeframe"] == "5m"
    assert items[0]["strategy_instance_id"] == derive_strategy_instance_id(
        strategy_id="ema_pullback",
        ticker="ETHUSDT.P",
        base_timeframe="5m",
        raw_spec={"anchor": 500},
    )
    assert body["invalid_files"] == []
    assert body["duplicate_identities"] == []


def test_response_has_no_raw_spec_or_state(tmp_path: Path) -> None:
    write_spec(tmp_path, "a.json")

    text = catalog_client(tmp_path).get(PATH).text

    assert "raw_spec" not in text
    assert "secret" not in text
    for forbidden in ("trade_cycle", "recovery", "risk_multiplier", "registered_spec"):
        assert forbidden not in text


def test_empty_catalog(tmp_path: Path) -> None:
    response = catalog_client(tmp_path).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "scanned_file_count": 0,
        "strategy_instances": [],
        "invalid_files": [],
        "duplicate_identities": [],
    }


def test_invalid_files_use_catalog_structure(tmp_path: Path) -> None:
    write_spec(tmp_path, "good.json")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "noenabled.json").write_text(
        json.dumps(
            {"ticker": "ETHUSDT.P", "base_timeframe": "5m", "strategy_id": "s", "raw_spec": {}}
        ),
        encoding="utf-8",
    )

    body = catalog_client(tmp_path).get(PATH).json()

    assert [item["source_path"] for item in body["strategy_instances"]] == ["good.json"]
    by_path = {item["source_path"]: item for item in body["invalid_files"]}
    assert set(by_path) == {"broken.json", "noenabled.json"}
    assert by_path["broken.json"]["error_code"] == "invalid_json"
    assert isinstance(by_path["broken.json"]["error_message"], str)
    assert by_path["noenabled.json"]["error_code"] == "missing_required_field"
    assert by_path["noenabled.json"]["error_message"] == "enabled"
    for item in body["invalid_files"]:
        assert set(item) == {"source_path", "error_code", "error_message"}


def test_invalid_file_with_null_error_message(tmp_path: Path) -> None:
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")

    body = catalog_client(tmp_path).get(PATH).json()

    assert body["invalid_files"] == [
        {"source_path": "list.json", "error_code": "invalid_root", "error_message": None}
    ]


def test_duplicate_identities_are_reported_and_excluded(tmp_path: Path) -> None:
    write_spec(tmp_path, "one.json", enabled=True)
    write_spec(tmp_path, "two.json", enabled=False)
    write_spec(tmp_path, "other.json", raw_spec={"anchor": 1000})

    body = catalog_client(tmp_path).get(PATH).json()

    assert [item["source_path"] for item in body["strategy_instances"]] == ["other.json"]
    duplicate_id = derive_strategy_instance_id(
        strategy_id="ema_pullback",
        ticker="ETHUSDT.P",
        base_timeframe="5m",
        raw_spec={"anchor": 500, "secret": "x"},
    )
    assert body["duplicate_identities"] == [
        {"strategy_instance_id": duplicate_id, "source_paths": ["one.json", "two.json"]}
    ]


def test_catalog_is_reread_on_every_request(tmp_path: Path) -> None:
    client = catalog_client(tmp_path)
    assert client.get(PATH).json()["strategy_instances"] == []

    write_spec(tmp_path, "a.json", enabled=True)
    first = client.get(PATH).json()["strategy_instances"]
    assert [item["enabled"] for item in first] == [True]

    write_spec(tmp_path, "a.json", enabled=False)
    second = client.get(PATH).json()["strategy_instances"]
    assert [item["enabled"] for item in second] == [False]

    (tmp_path / "a.json").unlink()
    assert client.get(PATH).json()["strategy_instances"] == []


def test_files_are_not_modified(tmp_path: Path) -> None:
    write_spec(tmp_path, "a.json")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    catalog_client(tmp_path).get(PATH)

    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_loader_called_once_per_request() -> None:
    calls = 0

    def loader() -> DeploymentCatalogSnapshot:
        nonlocal calls
        calls += 1
        return DeploymentCatalogSnapshot(
            scanned_file_count=0,
            accepted_deployments=(),
            invalid_files=(),
            duplicate_identities=(),
        )

    client = make_client(loader)
    client.get(PATH)
    client.get(PATH)

    assert calls == 2


def test_not_ready_when_application_not_ready() -> None:
    client = make_client(None, ready=False)

    response = client.get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_not_ready_when_loader_missing() -> None:
    response = make_client(None).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_catalog_unavailable() -> None:
    def loader() -> DeploymentCatalogSnapshot:
        raise DeploymentCatalogUnavailableError("deployment catalog directory scan failed")

    response = make_client(loader).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"status": "catalog_unavailable"}


def test_unexpected_failure_is_logged_and_returns_500() -> None:
    logger = RecordingLogger()

    def loader() -> DeploymentCatalogSnapshot:
        raise RuntimeError("boom")

    response = make_client(loader, logger=logger).get(PATH)

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}
    assert logger.exception_calls == ["Failed to list strategy instances"]


def test_spec_with_non_finite_number_currently_returns_500(tmp_path: Path) -> None:
    """Known defect (issue #20): load_snapshot() raises; the list answers 500."""
    write_spec(tmp_path, "good.json")
    (tmp_path / "huge.json").write_text(
        '{"enabled": true, "ticker": "ETHUSDT.P", "base_timeframe": "5m",'
        ' "strategy_id": "s", "raw_spec": {"x": 1e999}}',
        encoding="utf-8",
    )

    response = catalog_client(tmp_path).get(PATH)

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_other_methods_are_not_allowed(method: str) -> None:
    response = getattr(make_client(None), method)(PATH)

    assert response.status_code == 405


def test_built_application_serves_the_list(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    write_spec(specs, "a.json", enabled=False)
    environ = {
        "RUNTIME_SPECS_PATH": str(specs),
        "RUNTIME_JOURNAL_PATH": str(tmp_path / "journal" / "runtime.jsonl"),
        "RUNTIME_STATE_PATH": str(tmp_path / "state" / "runtime_state.jsonl"),
        "RUNTIME_STRATEGY_ENGINE_BASE_URL": "http://engine.invalid",
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_BASE_URL": "http://abi.invalid",
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS": "5",
        "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": "256",
    }

    app = build_application(environ)
    with TestClient(app) as client:
        response = client.get(PATH)

    assert response.status_code == 200
    items = response.json()["strategy_instances"]
    assert [(item["source_path"], item["enabled"]) for item in items] == [("a.json", False)]


def test_openapi_declares_both_503_bodies_and_the_500_body() -> None:
    schema = make_client(None).get("/openapi.json").json()
    responses = schema["paths"][PATH]["get"]["responses"]

    assert set(responses) >= {"200", "500", "503"}
    refs = {
        option["$ref"].rsplit("/", 1)[-1]
        for option in responses["503"]["content"]["application/json"]["schema"]["anyOf"]
    }
    assert refs == {"NotReadyResponse", "CatalogUnavailableResponse"}
    schemas = schema["components"]["schemas"]
    assert schemas["NotReadyResponse"]["properties"]["status"]["const"] == "not_ready"
    assert (
        schemas["CatalogUnavailableResponse"]["properties"]["status"]["const"]
        == "catalog_unavailable"
    )
    assert (
        responses["500"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        == "InternalErrorResponse"
    )
