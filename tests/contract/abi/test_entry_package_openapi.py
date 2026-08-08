import json
from pathlib import Path
from typing import Any

ENTRY_PACKAGE_PATH = (
    "/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/entry-package"
)


def test_authoritative_abi_openapi_matches_runtime_client_contract() -> None:
    document = read_authoritative_openapi()
    operation = document["paths"][ENTRY_PACKAGE_PATH]["put"]
    schemas = document["components"]["schemas"]

    assert document["openapi"] == "3.1.0"
    assert operation["operationId"] == "reconcileDesiredEntryPackage"
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EntryPackageRequest"
    }
    assert parameter_contract(operation["parameters"]) == {
        "strategy_instance_id": {"type": "string", "minLength": 1},
        "trade_cycle_id": {"type": "string", "minLength": 1},
    }
    assert set(operation["responses"]) == {"200", "400", "415", "422", "500"}

    assert schemas["EntryPackageRequest"] == {
        "oneOf": [
            {"$ref": "#/components/schemas/PackagePresentRequest"},
            {"$ref": "#/components/schemas/PackageAbsentRequest"},
        ]
    }
    assert_request_variant(schemas["PackagePresentRequest"], present=True)
    assert_request_variant(schemas["PackageAbsentRequest"], present=False)
    assert_desired_entry_schema(schemas["DesiredEntry"])
    assert_success_schemas(schemas, operation)
    assert_error_schemas(schemas, operation)


def test_authoritative_openapi_examples_use_mandatory_risk_for_both_requests() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][ENTRY_PACKAGE_PATH]["put"]["requestBody"]["content"][
        "application/json"
    ]["examples"]

    assert examples["package"]["value"]["risk_multiplier"] == "1"
    assert examples["package"]["value"]["desired_entry"] is not None
    assert examples["absence"]["value"] == {
        "ticker": "BTCUSDT.P",
        "desired_entry": None,
        "risk_multiplier": "1",
    }


def read_authoritative_openapi() -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[3]
    path = (
        repository_root.parent
        / "abi_executor_bot"
        / "docs"
        / "openapi"
        / "abi-entry-package-api-v1.json"
    )
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def parameter_contract(parameters: list[dict[str, Any]]) -> dict[str, object]:
    assert all(parameter["in"] == "path" for parameter in parameters)
    assert all(parameter["required"] is True for parameter in parameters)
    return {parameter["name"]: parameter["schema"] for parameter in parameters}


def assert_request_variant(schema: dict[str, Any], *, present: bool) -> None:
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"ticker", "desired_entry", "risk_multiplier"}
    assert schema["properties"]["ticker"] == {"type": "string", "minLength": 1}
    assert schema["properties"]["risk_multiplier"] == {
        "type": "string",
        "format": "positive-exact-decimal",
    }
    expected_desired = (
        {"$ref": "#/components/schemas/DesiredEntry"} if present else {"type": "null"}
    )
    assert schema["properties"]["desired_entry"] == expected_desired


def assert_desired_entry_schema(schema: dict[str, Any]) -> None:
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "side",
        "source_plan_bar_open_time_ms",
        "planned_entry_price",
        "initial_stop_price",
        "initial_take_price",
        "locked_exit_profile",
    }
    properties = schema["properties"]
    assert properties["side"] == {"type": "string", "enum": ["long", "short"]}
    assert properties["source_plan_bar_open_time_ms"] == {"type": "integer"}
    assert properties["planned_entry_price"] == {
        "type": "string",
        "format": "exact-decimal",
    }
    assert properties["initial_stop_price"] == {
        "type": "string",
        "format": "exact-decimal",
    }
    assert properties["initial_take_price"] == {
        "type": "string",
        "format": "positive-exact-decimal",
    }
    assert properties["locked_exit_profile"] == {"type": "string"}


def assert_success_schemas(schemas: dict[str, Any], operation: dict[str, Any]) -> None:
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success == {
        "oneOf": [
            {"$ref": "#/components/schemas/EntryPackageAppliedResponse"},
            {"$ref": "#/components/schemas/EntryPackageAbsentResponse"},
        ]
    }

    applied = schemas["EntryPackageAppliedResponse"]
    assert applied["additionalProperties"] is False
    assert set(applied["required"]) == {
        "strategy_instance_id",
        "trade_cycle_id",
        "status",
        "applied_desired_entry",
        "calculated_quantity",
    }
    assert applied["properties"]["status"] == {"const": "entry_package_applied"}
    assert "accepted_risk_multiplier" not in applied["properties"]
    assert applied["properties"]["calculated_quantity"] == {
        "type": "string",
        "format": "exact-decimal",
    }

    absent = schemas["EntryPackageAbsentResponse"]
    assert absent["additionalProperties"] is False
    assert set(absent["required"]) == {
        "strategy_instance_id",
        "trade_cycle_id",
        "status",
    }
    assert absent["properties"]["status"] == {"const": "entry_package_absent"}


def assert_error_schemas(schemas: dict[str, Any], operation: dict[str, Any]) -> None:
    response_refs = {
        "400": ("MalformedJsonError", "malformed_json"),
        "415": ("UnsupportedMediaTypeError", "unsupported_media_type"),
        "422": ("ValidationError", "validation_failed"),
        "500": ("InternalError", "internal_error"),
    }
    for status, (schema_name, code) in response_refs.items():
        response_schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{schema_name}"}
        resolved = resolve_schema_reference(schemas, schema_name)
        assert resolved["additionalProperties"] is False
        assert resolved["required"] == ["error"]
        error = resolved["properties"]["error"]
        assert error["additionalProperties"] is False
        assert error["properties"]["code"] == {"const": code}
        assert error["properties"]["message"] == {"type": "string", "minLength": 1}
        if status == "422":
            assert set(error["required"]) == {"code", "message", "details"}
            assert error["properties"]["details"]["minItems"] == 1
            assert error["properties"]["details"]["items"] == {
                "$ref": "#/components/schemas/ValidationDetail"
            }
        else:
            assert set(error["required"]) == {"code", "message"}
            assert "details" not in error["properties"]

    validation_detail = schemas["ValidationDetail"]
    assert validation_detail["additionalProperties"] is False
    assert set(validation_detail["required"]) == {"path", "message"}
    assert validation_detail["properties"] == {
        "path": {"type": "string"},
        "message": {"type": "string"},
    }


def resolve_schema_reference(schemas: dict[str, Any], schema_name: str) -> dict[str, Any]:
    schema = schemas[schema_name]
    reference = schema.get("$ref")
    if reference is None:
        return schema
    prefix = "#/components/schemas/"
    assert reference.startswith(prefix)
    return schemas[reference.removeprefix(prefix)]
