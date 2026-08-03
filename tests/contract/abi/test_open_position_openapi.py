import json
from pathlib import Path
from typing import Any

import pytest

from strategy_runtime.infrastructure.abi.open_position_codec import decode_open_position_response
from strategy_runtime.runtime.open_position.models import OpenPositionLookupResponse

OPEN_POSITION_PATH = (
    "/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position"
)


class MissingAuthoritativeOpenApiDocument(RuntimeError):
    """Raised when the sibling `abi_executor_bot` checkout is not present."""


def test_authoritative_abi_openapi_matches_runtime_client_contract() -> None:
    document = read_authoritative_openapi()
    operation = document["paths"][OPEN_POSITION_PATH]["get"]
    schemas = document["components"]["schemas"]

    assert document["openapi"] == "3.1.0"
    assert operation["operationId"] == "getOpenPositionForTradeCycle"
    assert parameter_contract(operation["parameters"]) == {
        "strategy_instance_id": {"type": "string", "minLength": 1},
        "trade_cycle_id": {"type": "string", "minLength": 1},
    }
    assert set(operation["responses"]) == {"200", "422", "500"}

    assert_success_schemas(schemas, operation)
    assert_error_schemas(schemas, operation)


def test_authoritative_openapi_examples_decode_successfully_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][OPEN_POSITION_PATH]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["examples"]

    open_result = decode_open_position_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(examples["open"]["value"]).encode("utf-8"),
    )
    assert open_result == OpenPositionLookupResponse(
        position_open=True,
        first_fill_at_ms=examples["open"]["value"]["first_fill_at_ms"],
        average_entry_price=examples["open"]["value"]["average_entry_price"],
    )

    closed_result = decode_open_position_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(examples["closed"]["value"]).encode("utf-8"),
    )
    assert closed_result == OpenPositionLookupResponse(position_open=False)


def test_authoritative_openapi_business_error_examples_decode_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][OPEN_POSITION_PATH]["get"]["responses"]["422"]["content"][
        "application/json"
    ]["examples"]

    for name in ("validation_failed", "unknown_trade_cycle_binding", "unsupported_exchange_scope"):
        with pytest.raises(Exception) as raised:  # noqa: PT011 - asserting the typed public error below
            decode_open_position_response(
                status_code=422,
                content_type="application/json",
                content=json.dumps(examples[name]["value"]).encode("utf-8"),
            )
        assert raised.value.__class__.__name__ == "OpenPositionLookupPublicError"
        assert raised.value.code == examples[name]["value"]["error"]["code"]  # type: ignore[attr-defined]


def test_missing_sibling_checkout_raises_an_actionable_error(tmp_path: Path) -> None:
    fake_repository_root = tmp_path / "strategy_runtime"
    fake_repository_root.mkdir()

    with pytest.raises(MissingAuthoritativeOpenApiDocument, match="canonical sibling checkout"):
        _resolve_authoritative_openapi_path(fake_repository_root)


def read_authoritative_openapi() -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[3]
    path = _resolve_authoritative_openapi_path(repository_root)
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _resolve_authoritative_openapi_path(repository_root: Path) -> Path:
    path = (
        repository_root.parent
        / "abi_executor_bot"
        / "docs"
        / "openapi"
        / "abi-open-position-lookup-api-v1.json"
    )
    if not path.is_file():
        raise MissingAuthoritativeOpenApiDocument(
            f"Authoritative ABI OpenAPI document not found at {path}. "
            "This contract test requires the canonical sibling checkout "
            "layout BBB_project/{strategy_runtime,abi_executor_bot}, with "
            "abi_executor_bot checked out at "
            "ea5a18903f28d89f5f97a6b9a8c82ae395bf720a next to this "
            "repository."
        )
    return path


def parameter_contract(parameters: list[dict[str, Any]]) -> dict[str, object]:
    assert all(parameter["in"] == "path" for parameter in parameters)
    assert all(parameter["required"] is True for parameter in parameters)
    return {parameter["name"]: parameter["schema"] for parameter in parameters}


def assert_success_schemas(schemas: dict[str, Any], operation: dict[str, Any]) -> None:
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success == {"$ref": "#/components/schemas/OpenPositionResponse"}

    response = schemas["OpenPositionResponse"]
    assert response == {
        "oneOf": [
            {"$ref": "#/components/schemas/OpenPositionOpenResponse"},
            {"$ref": "#/components/schemas/OpenPositionClosedResponse"},
        ]
    }

    open_schema = schemas["OpenPositionOpenResponse"]
    assert open_schema["additionalProperties"] is False
    assert set(open_schema["required"]) == {
        "position_open",
        "first_fill_at_ms",
        "average_entry_price",
    }
    assert open_schema["properties"]["position_open"] == {"const": True}
    assert open_schema["properties"]["first_fill_at_ms"] == {
        "type": "integer",
        "exclusiveMinimum": 0,
    }
    assert open_schema["properties"]["average_entry_price"] == {
        "type": "string",
        "format": "positive-exact-decimal",
    }

    closed_schema = schemas["OpenPositionClosedResponse"]
    assert closed_schema["additionalProperties"] is False
    assert set(closed_schema["required"]) == {
        "position_open",
        "first_fill_at_ms",
        "average_entry_price",
    }
    assert closed_schema["properties"]["position_open"] == {"const": False}
    assert closed_schema["properties"]["first_fill_at_ms"] == {"type": "null"}
    assert closed_schema["properties"]["average_entry_price"] == {"type": "null"}


def assert_error_schemas(schemas: dict[str, Any], operation: dict[str, Any]) -> None:
    business_error = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert business_error == {"$ref": "#/components/schemas/OpenPositionBusinessError"}
    assert schemas["OpenPositionBusinessError"] == {
        "oneOf": [
            {"$ref": "#/components/schemas/ValidationFailedError"},
            {"$ref": "#/components/schemas/UnknownTradeCycleBindingError"},
            {"$ref": "#/components/schemas/UnsupportedExchangeScopeError"},
        ]
    }

    validation_failed = resolve_error_schema(schemas["ValidationFailedError"])
    assert validation_failed["additionalProperties"] is False
    assert set(validation_failed["required"]) == {"code", "message", "details"}
    assert validation_failed["properties"]["code"] == {"const": "validation_failed"}
    assert validation_failed["properties"]["details"]["minItems"] == 1
    assert validation_failed["properties"]["details"]["items"] == {
        "$ref": "#/components/schemas/ValidationDetail"
    }

    for schema_name, code in (
        ("UnknownTradeCycleBindingError", "unknown_trade_cycle_binding"),
        ("UnsupportedExchangeScopeError", "unsupported_exchange_scope"),
    ):
        resolved = resolve_error_schema(schemas[schema_name])
        assert resolved["additionalProperties"] is False
        assert set(resolved["required"]) == {"code", "message"}
        assert "details" not in resolved["properties"]
        assert resolved["properties"]["code"] == {"const": code}

    validation_detail = schemas["ValidationDetail"]
    assert validation_detail["additionalProperties"] is False
    assert set(validation_detail["required"]) == {"path", "message"}
    assert validation_detail["properties"] == {
        "path": {"type": "string"},
        "message": {"type": "string"},
    }

    internal_error_schema = operation["responses"]["500"]["content"]["application/json"]["schema"]
    assert internal_error_schema == {"$ref": "#/components/schemas/InternalError"}
    internal_error = resolve_error_schema(schemas["InternalError"])
    assert internal_error["additionalProperties"] is False
    assert set(internal_error["required"]) == {"code", "message"}
    assert "details" not in internal_error["properties"]
    assert internal_error["properties"]["code"] == {"const": "internal_error"}


def resolve_error_schema(schema: dict[str, Any]) -> dict[str, Any]:
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["error"]
    return schema["properties"]["error"]
