import json
from pathlib import Path
from typing import Any

import pytest

from strategy_runtime.infrastructure.abi.position_management_codec import (
    decode_apply_protection_response,
    decode_close_position_response,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionPublicError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.recipes.position_management import DesiredProtection

PROTECTION_PATH = (
    "/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/protection"
)
OPEN_POSITION_PATH = (
    "/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position"
)


class MissingAuthoritativeOpenApiDocument(RuntimeError):
    """Raised when the sibling `abi_executor_bot` checkout is not present."""


def test_authoritative_abi_openapi_matches_runtime_apply_protection_contract() -> None:
    document = read_authoritative_openapi()
    operation = document["paths"][PROTECTION_PATH]["put"]
    schemas = document["components"]["schemas"]

    assert document["openapi"] == "3.1.0"
    assert operation["operationId"] == "applyPositionProtection"
    assert parameter_contract(operation["parameters"]) == {
        "strategy_instance_id": {"type": "string", "minLength": 1},
        "trade_cycle_id": {"type": "string", "minLength": 1},
    }
    assert set(operation["responses"]) == {"200", "400", "415", "422", "500"}

    price_format = {"type": "string", "format": "positive-exact-decimal"}
    nullable_price_format = {"oneOf": [price_format, {"type": "null"}]}

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": "#/components/schemas/ProtectionRequest"}
    request = schemas["ProtectionRequest"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"stop_price", "take_price"}
    assert request["properties"]["stop_price"] == price_format
    assert request["properties"]["take_price"] == nullable_price_format

    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema == {"$ref": "#/components/schemas/ProtectionAppliedResponse"}
    success = schemas["ProtectionAppliedResponse"]
    assert success["additionalProperties"] is False
    assert set(success["required"]) == {
        "strategy_instance_id",
        "trade_cycle_id",
        "status",
        "stop_price",
        "take_price",
    }
    assert success["properties"]["status"] == {"const": "protection_applied"}
    assert success["properties"]["stop_price"] == price_format
    assert success["properties"]["take_price"] == nullable_price_format

    error_schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert error_schema == {"$ref": "#/components/schemas/ProtectionBusinessError"}
    assert schemas["ProtectionBusinessError"] == {
        "oneOf": [
            {"$ref": "#/components/schemas/ValidationFailedError"},
            {"$ref": "#/components/schemas/UnknownTradeCycleBindingError"},
            {"$ref": "#/components/schemas/UnsupportedExchangeScopeError"},
            {"$ref": "#/components/schemas/PositionNotOpenError"},
        ]
    }
    assert resolve_error_schema(schemas["PositionNotOpenError"])["properties"]["code"] == {
        "const": "position_not_open"
    }

    validation_detail = schemas["ValidationDetail"]
    assert validation_detail["additionalProperties"] is False
    assert set(validation_detail["required"]) == {"path", "message"}
    assert validation_detail["properties"] == {
        "path": {"type": "string"},
        "message": {"type": "string"},
    }

    assert operation["responses"]["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MalformedJsonError"
    }
    malformed_json_schema = resolve_schema_ref(schemas, schemas["MalformedJsonError"])
    assert resolve_error_schema(malformed_json_schema)["properties"]["code"] == {
        "const": "malformed_json"
    }
    assert operation["responses"]["415"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UnsupportedMediaTypeError"
    }
    assert resolve_error_schema(schemas["UnsupportedMediaTypeError"])["properties"]["code"] == {
        "const": "unsupported_media_type"
    }

    internal_error_schema = operation["responses"]["500"]["content"]["application/json"]["schema"]
    assert internal_error_schema == {"$ref": "#/components/schemas/InternalError"}
    assert resolve_error_schema(schemas["InternalError"])["properties"]["code"] == {
        "const": "internal_error"
    }


def test_authoritative_abi_openapi_matches_runtime_close_position_contract() -> None:
    document = read_authoritative_openapi()
    operation = document["paths"][OPEN_POSITION_PATH]["delete"]
    schemas = document["components"]["schemas"]

    assert operation["operationId"] == "closeTradeCyclePosition"
    assert parameter_contract(operation["parameters"]) == {
        "strategy_instance_id": {"type": "string", "minLength": 1},
        "trade_cycle_id": {"type": "string", "minLength": 1},
    }
    assert set(operation["responses"]) == {"200", "422", "500"}
    assert "requestBody" not in operation

    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema == {"$ref": "#/components/schemas/TradeCycleClosedResponse"}
    success = schemas["TradeCycleClosedResponse"]
    assert success["additionalProperties"] is False
    assert set(success["required"]) == {"strategy_instance_id", "trade_cycle_id", "status"}
    assert success["properties"]["status"] == {"const": "trade_cycle_closed"}

    error_schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert error_schema == {"$ref": "#/components/schemas/CloseBusinessError"}
    assert schemas["CloseBusinessError"] == {
        "oneOf": [
            {"$ref": "#/components/schemas/ValidationFailedError"},
            {"$ref": "#/components/schemas/UnknownTradeCycleBindingError"},
            {"$ref": "#/components/schemas/UnsupportedExchangeScopeError"},
        ]
    }

    internal_error_schema = operation["responses"]["500"]["content"]["application/json"]["schema"]
    assert internal_error_schema == {"$ref": "#/components/schemas/InternalError"}
    assert resolve_error_schema(schemas["InternalError"])["properties"]["code"] == {
        "const": "internal_error"
    }


def test_authoritative_protection_examples_decode_successfully_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    example = document["paths"][PROTECTION_PATH]["put"]["responses"]["200"]["content"][
        "application/json"
    ]["examples"]["applied"]["value"]

    command = ApplyProtectionCommand(
        strategy_instance_id=example["strategy_instance_id"],
        trade_cycle_id=example["trade_cycle_id"],
        desired_protection=DesiredProtection(
            stop_price=example["stop_price"], take_price=example["take_price"]
        ),
    )

    result = decode_apply_protection_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(example).encode("utf-8"),
        command=command,
    )
    assert result == ProtectionAppliedConfirmation(
        strategy_instance_id=example["strategy_instance_id"],
        trade_cycle_id=example["trade_cycle_id"],
        confirmed_protection=DesiredProtection(
            stop_price=example["stop_price"], take_price=example["take_price"]
        ),
    )


def test_authoritative_close_example_decodes_successfully_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    example = document["paths"][OPEN_POSITION_PATH]["delete"]["responses"]["200"]["content"][
        "application/json"
    ]["examples"]["closed"]["value"]

    command = ClosePositionCommand(
        strategy_instance_id=example["strategy_instance_id"],
        trade_cycle_id=example["trade_cycle_id"],
    )

    result = decode_close_position_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(example).encode("utf-8"),
        command=command,
    )
    assert result == PositionClosedConfirmation(
        strategy_instance_id=example["strategy_instance_id"],
        trade_cycle_id=example["trade_cycle_id"],
    )


def test_authoritative_protection_business_error_examples_decode_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][PROTECTION_PATH]["put"]["responses"]["422"]["content"][
        "application/json"
    ]["examples"]
    command = ApplyProtectionCommand(
        strategy_instance_id="instance",
        trade_cycle_id="cycle",
        desired_protection=DesiredProtection("1", None),
    )

    for name in (
        "validation_failed",
        "unknown_trade_cycle_binding",
        "unsupported_exchange_scope",
        "position_not_open",
    ):
        with pytest.raises(PositionManagementExecutionPublicError) as raised:
            decode_apply_protection_response(
                status_code=422,
                content_type="application/json",
                content=json.dumps(examples[name]["value"]).encode("utf-8"),
                command=command,
            )
        assert raised.value.code == examples[name]["value"]["error"]["code"]


def test_authoritative_close_business_error_examples_decode_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][OPEN_POSITION_PATH]["delete"]["responses"]["422"]["content"][
        "application/json"
    ]["examples"]
    command = ClosePositionCommand(strategy_instance_id="instance", trade_cycle_id="cycle")

    for name in ("validation_failed", "unknown_trade_cycle_binding", "unsupported_exchange_scope"):
        with pytest.raises(PositionManagementExecutionPublicError) as raised:
            decode_close_position_response(
                status_code=422,
                content_type="application/json",
                content=json.dumps(examples[name]["value"]).encode("utf-8"),
                command=command,
            )
        assert raised.value.code == examples[name]["value"]["error"]["code"]


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
        / "abi-position-management-api-v1.json"
    )
    if not path.is_file():
        raise MissingAuthoritativeOpenApiDocument(
            f"Authoritative ABI OpenAPI document not found at {path}. "
            "This contract test requires the canonical sibling checkout "
            "layout BBB_project/{strategy_runtime,abi_executor_bot}, with "
            "abi_executor_bot checked out next to this repository."
        )
    return path


def parameter_contract(parameters: list[dict[str, Any]]) -> dict[str, object]:
    assert all(parameter["in"] == "path" for parameter in parameters)
    assert all(parameter["required"] is True for parameter in parameters)
    return {parameter["name"]: parameter["schema"] for parameter in parameters}


def resolve_error_schema(schema: dict[str, Any]) -> dict[str, Any]:
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["error"]
    return schema["properties"]["error"]


def resolve_schema_ref(schemas: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    name = ref.removeprefix("#/components/schemas/")
    return resolve_schema_ref(schemas, schemas[name])
