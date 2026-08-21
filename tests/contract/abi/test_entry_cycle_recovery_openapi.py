import json
from pathlib import Path
from typing import Any

import pytest

from strategy_runtime.infrastructure.abi.entry_cycle_recovery_codec import (
    decode_recovery_state_response,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryUnavailable,
    AbiEntryCycleRecoveryUnknownTradeCycleBinding,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import (
    EntryOrderLiveRecoveryState,
    EntryOrderNotFoundRecoveryState,
    PositionOpenRecoveryState,
    RecoveryStateAppliedEntryPackage,
    TerminalAfterFillRecoveryState,
    TerminalWithoutFillRecoveryState,
)
from strategy_runtime.runtime.abi.entry_package_models import EntryPackageWireDesiredEntry

RECOVERY_STATE_PATH = (
    "/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/recovery-state"
)


class MissingAuthoritativeOpenApiDocument(RuntimeError):
    """Raised when the sibling `abi_executor_bot` checkout is not present."""


def test_authoritative_abi_openapi_matches_runtime_client_contract() -> None:
    document = read_authoritative_openapi()
    operation = document["paths"][RECOVERY_STATE_PATH]["get"]
    schemas = document["components"]["schemas"]

    assert document["openapi"] == "3.1.0"
    assert operation["operationId"] == "getEntryCycleRecoveryState"
    assert parameter_contract(operation["parameters"]) == {
        "strategy_instance_id": {"type": "string", "minLength": 1},
        "trade_cycle_id": {"type": "string", "minLength": 1},
    }
    assert set(operation["responses"]) == {"200", "422", "500"}

    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success == {"$ref": "#/components/schemas/RecoveryStateResponse"}
    assert schemas["RecoveryStateResponse"] == {
        "oneOf": [
            {"$ref": "#/components/schemas/EntryOrderLiveResponse"},
            {"$ref": "#/components/schemas/EntryOrderNotFoundResponse"},
            {"$ref": "#/components/schemas/PositionOpenResponse"},
            {"$ref": "#/components/schemas/TerminalWithoutFillResponse"},
            {"$ref": "#/components/schemas/TerminalAfterFillResponse"},
        ]
    }

    business_error = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert business_error == {"$ref": "#/components/schemas/RecoveryStateBusinessError"}
    assert schemas["RecoveryStateBusinessError"] == {
        "oneOf": [
            {"$ref": "#/components/schemas/ValidationFailedError"},
            {"$ref": "#/components/schemas/UnknownTradeCycleBindingError"},
        ]
    }

    unknown_binding = resolve_error_schema(schemas["UnknownTradeCycleBindingError"])
    assert set(unknown_binding["required"]) == {"code", "message"}
    assert unknown_binding["properties"]["code"] == {"const": "unknown_trade_cycle_binding"}

    internal_error_schema = operation["responses"]["500"]["content"]["application/json"]["schema"]
    assert internal_error_schema == {"$ref": "#/components/schemas/InternalError"}
    internal_error = resolve_error_schema(schemas["InternalError"])
    assert set(internal_error["required"]) == {"code", "message"}
    assert internal_error["properties"]["code"] == {"const": "internal_error"}


def test_authoritative_openapi_success_examples_decode_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][RECOVERY_STATE_PATH]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["examples"]

    entry_order_live = decode_recovery_state_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(examples["entry_order_live"]["value"]).encode("utf-8"),
    )
    assert entry_order_live == EntryOrderLiveRecoveryState(
        applied_entry_package=_applied_entry_package_from(
            examples["entry_order_live"]["value"]["applied_entry_package"]
        )
    )

    entry_order_not_found = decode_recovery_state_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(examples["entry_order_not_found"]["value"]).encode("utf-8"),
    )
    assert entry_order_not_found == EntryOrderNotFoundRecoveryState()

    position_open_value = examples["position_open"]["value"]
    position_open = decode_recovery_state_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(position_open_value).encode("utf-8"),
    )
    assert position_open == PositionOpenRecoveryState(
        applied_entry_package=_applied_entry_package_from(
            position_open_value["applied_entry_package"]
        ),
        first_fill_at_ms=position_open_value["first_fill_at_ms"],
        average_entry_price=position_open_value["average_entry_price"],
    )

    terminal_without_fill = decode_recovery_state_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(examples["terminal_without_fill"]["value"]).encode("utf-8"),
    )
    assert terminal_without_fill == TerminalWithoutFillRecoveryState()

    terminal_after_fill = decode_recovery_state_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(examples["terminal_after_fill"]["value"]).encode("utf-8"),
    )
    assert terminal_after_fill == TerminalAfterFillRecoveryState()


def test_authoritative_openapi_unknown_binding_example_decodes_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    examples = document["paths"][RECOVERY_STATE_PATH]["get"]["responses"]["422"]["content"][
        "application/json"
    ]["examples"]

    with pytest.raises(AbiEntryCycleRecoveryUnknownTradeCycleBinding):
        decode_recovery_state_response(
            status_code=422,
            content_type="application/json",
            content=json.dumps(examples["unknown_trade_cycle_binding"]["value"]).encode("utf-8"),
        )


def test_authoritative_openapi_internal_error_example_decodes_via_runtime_codec() -> None:
    document = read_authoritative_openapi()
    example = document["paths"][RECOVERY_STATE_PATH]["get"]["responses"]["500"]["content"][
        "application/json"
    ]["example"]

    with pytest.raises(AbiEntryCycleRecoveryUnavailable):
        decode_recovery_state_response(
            status_code=500,
            content_type="application/json",
            content=json.dumps(example).encode("utf-8"),
        )


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
        / "abi-entry-cycle-recovery-api-v1.json"
    )
    if not path.is_file():
        raise MissingAuthoritativeOpenApiDocument(
            f"Authoritative ABI OpenAPI document not found at {path}. "
            "This contract test requires the canonical sibling checkout "
            "layout BBB_project/{strategy_runtime,abi_executor_bot}, with "
            "abi_executor_bot's abi-entry-cycle-recovery-v1 change checked "
            "out next to this repository."
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


def _applied_entry_package_from(payload: dict[str, Any]) -> RecoveryStateAppliedEntryPackage:
    desired = payload["applied_desired_entry"]
    return RecoveryStateAppliedEntryPackage(
        applied_desired_entry=EntryPackageWireDesiredEntry(
            side=desired["side"],
            source_plan_bar_open_time_ms=desired["source_plan_bar_open_time_ms"],
            planned_entry_price=desired["planned_entry_price"],
            initial_stop_price=desired["initial_stop_price"],
            initial_take_price=desired["initial_take_price"],
            locked_exit_profile=desired["locked_exit_profile"],
        ),
        calculated_quantity=payload["calculated_quantity"],
    )
