"""Strict JSON codec for the ABI entry-package HTTP contract."""

import json
from typing import Literal, NoReturn, cast

from strategy_runtime.runtime.abi.entry_package_errors import AbiEntryPackageProtocolError
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageApplied,
    EntryPackageInternalError,
    EntryPackageMalformedJson,
    EntryPackageRequest,
    EntryPackageResult,
    EntryPackageUnsupportedMediaType,
    EntryPackageValidationDetail,
    EntryPackageValidationFailed,
    EntryPackageWireDesiredEntry,
)

_APPLIED_FIELDS = frozenset(
    {
        "strategy_instance_id",
        "trade_cycle_id",
        "status",
        "applied_desired_entry",
        "calculated_quantity",
    }
)
_ABSENT_FIELDS = frozenset({"strategy_instance_id", "trade_cycle_id", "status"})
_DESIRED_ENTRY_FIELDS = frozenset(
    {
        "side",
        "source_plan_bar_open_time_ms",
        "planned_entry_price",
        "initial_stop_price",
        "initial_take_price",
        "locked_exit_profile",
    }
)
_PUBLIC_ERROR_CODES = {
    400: "malformed_json",
    415: "unsupported_media_type",
    422: "validation_failed",
    500: "internal_error",
}


def encode_entry_package_request(request: EntryPackageRequest) -> dict[str, object]:
    """Create the exact three-field ABI request body."""
    desired_entry: dict[str, object] | None = None
    if request.desired_entry is not None:
        desired_entry = _encode_desired_entry(request.desired_entry)
    return {
        "ticker": request.ticker,
        "desired_entry": desired_entry,
        "risk_multiplier": request.risk_multiplier,
    }


def decode_entry_package_response(
    *,
    status_code: int,
    content_type: str | None,
    content: bytes,
    request: EntryPackageRequest,
) -> EntryPackageResult:
    """Decode one response or fail closed with a typed protocol error."""
    _require_json_content_type(content_type)
    payload = _load_strict_json(content)

    if status_code == 200:
        return _decode_success(payload, request)
    if status_code in _PUBLIC_ERROR_CODES:
        return _decode_public_error(status_code, payload)
    raise AbiEntryPackageProtocolError(f"undocumented ABI HTTP status: {status_code}")


def _encode_desired_entry(value: EntryPackageWireDesiredEntry) -> dict[str, object]:
    return {
        "side": value.side,
        "source_plan_bar_open_time_ms": value.source_plan_bar_open_time_ms,
        "planned_entry_price": value.planned_entry_price,
        "initial_stop_price": value.initial_stop_price,
        "initial_take_price": value.initial_take_price,
        "locked_exit_profile": value.locked_exit_profile,
    }


def _decode_success(payload: object, request: EntryPackageRequest) -> EntryPackageResult:
    try:
        body = _closed_object(payload, None, "success response")
        status = body.get("status")
        if status == EntryPackageApplied.status:
            _require_exact_fields(body, _APPLIED_FIELDS, "applied response")
            result: EntryPackageApplied | EntryPackageAbsent = EntryPackageApplied(
                strategy_instance_id=_non_empty_string(
                    body["strategy_instance_id"], "strategy_instance_id"
                ),
                trade_cycle_id=_non_empty_string(body["trade_cycle_id"], "trade_cycle_id"),
                applied_desired_entry=_decode_desired_entry(body["applied_desired_entry"]),
                calculated_quantity=_string(body["calculated_quantity"], "calculated_quantity"),
            )
        elif status == EntryPackageAbsent.status:
            _require_exact_fields(body, _ABSENT_FIELDS, "absent response")
            result = EntryPackageAbsent(
                strategy_instance_id=_non_empty_string(
                    body["strategy_instance_id"], "strategy_instance_id"
                ),
                trade_cycle_id=_non_empty_string(body["trade_cycle_id"], "trade_cycle_id"),
            )
        else:
            raise ValueError("success status is not an approved literal")
    except (KeyError, TypeError, ValueError) as exc:
        raise AbiEntryPackageProtocolError(f"invalid ABI success response: {exc}") from exc

    if result.strategy_instance_id != request.strategy_instance_id:
        raise AbiEntryPackageProtocolError(
            "ABI success strategy_instance_id does not match request"
        )
    if result.trade_cycle_id != request.trade_cycle_id:
        raise AbiEntryPackageProtocolError("ABI success trade_cycle_id does not match request")
    return result


def _decode_desired_entry(payload: object) -> EntryPackageWireDesiredEntry:
    body = _closed_object(payload, _DESIRED_ENTRY_FIELDS, "applied_desired_entry")
    side = body["side"]
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    source_open_time = body["source_plan_bar_open_time_ms"]
    if type(source_open_time) is not int:
        raise TypeError("source_plan_bar_open_time_ms must be a JSON integer")
    return EntryPackageWireDesiredEntry(
        side=cast("Literal['long', 'short']", side),
        source_plan_bar_open_time_ms=source_open_time,
        planned_entry_price=_string(body["planned_entry_price"], "planned_entry_price"),
        initial_stop_price=_string(body["initial_stop_price"], "initial_stop_price"),
        initial_take_price=_string(body["initial_take_price"], "initial_take_price"),
        locked_exit_profile=_string(body["locked_exit_profile"], "locked_exit_profile"),
    )


def _decode_public_error(status_code: int, payload: object) -> EntryPackageResult:
    try:
        expected_code = _PUBLIC_ERROR_CODES[status_code]
        envelope = _closed_object(payload, frozenset({"error"}), "error envelope")
        error = _closed_object(envelope["error"], None, "error object")
        expected_fields = (
            frozenset({"code", "message", "details"})
            if expected_code == "validation_failed"
            else frozenset({"code", "message"})
        )
        _require_exact_fields(error, expected_fields, "error object")
        if error["code"] != expected_code:
            raise ValueError(f"HTTP {status_code} requires error code {expected_code!r}")
        message = _non_empty_string(error["message"], "error.message")
        if expected_code == "malformed_json":
            return EntryPackageMalformedJson(message=message)
        if expected_code == "unsupported_media_type":
            return EntryPackageUnsupportedMediaType(message=message)
        if expected_code == "internal_error":
            return EntryPackageInternalError(message=message)
        return EntryPackageValidationFailed(
            message=message,
            details=_decode_validation_details(error["details"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AbiEntryPackageProtocolError(f"invalid ABI public error response: {exc}") from exc


def _decode_validation_details(payload: object) -> tuple[EntryPackageValidationDetail, ...]:
    if type(payload) is not list or len(payload) == 0:
        raise ValueError("error.details must be a non-empty array")
    details: list[EntryPackageValidationDetail] = []
    for index, raw_detail in enumerate(payload):
        detail = _closed_object(
            raw_detail, frozenset({"path", "message"}), f"error.details[{index}]"
        )
        details.append(
            EntryPackageValidationDetail(
                path=_string(detail["path"], f"error.details[{index}].path"),
                message=_string(detail["message"], f"error.details[{index}].message"),
            )
        )
    return tuple(details)


def _load_strict_json(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_fields,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AbiEntryPackageProtocolError(f"invalid ABI JSON response: {exc}") from exc


def _reject_duplicate_object_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object field: {key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")


def _require_json_content_type(value: str | None) -> None:
    if value is None:
        raise AbiEntryPackageProtocolError("ABI response is missing content-type")
    parts = value.split(";")
    if parts[0].strip().lower() != "application/json":
        raise AbiEntryPackageProtocolError("ABI response content-type is not application/json")

    seen_charset = False
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or "=" not in parameter:
            raise AbiEntryPackageProtocolError("ABI response content-type is malformed")
        name, raw_value = parameter.split("=", 1)
        if name.strip().lower() != "charset" or seen_charset:
            raise AbiEntryPackageProtocolError(
                "ABI response content-type has unsupported parameters"
            )
        charset = raw_value.strip()
        if len(charset) >= 2 and charset[0] == charset[-1] == '"':
            charset = charset[1:-1]
        if charset.lower() != "utf-8":
            raise AbiEntryPackageProtocolError("ABI response charset is not UTF-8")
        seen_charset = True


def _closed_object(value: object, fields: frozenset[str] | None, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be a JSON object")
    result = cast("dict[str, object]", value)
    if fields is not None:
        _require_exact_fields(result, fields, name)
    return result


def _require_exact_fields(value: dict[str, object], fields: frozenset[str], name: str) -> None:
    actual = frozenset(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise ValueError(f"{name} fields differ; missing={missing}, unknown={unknown}")


def _string(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    return value


def _non_empty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if len(result) == 0:
        raise ValueError(f"{name} must be non-empty")
    return result
