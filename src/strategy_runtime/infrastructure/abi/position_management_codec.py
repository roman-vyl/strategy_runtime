"""Strict JSON codec for the ABI position-management HTTP contract."""

import json
from typing import NoReturn, cast

from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionProtocolError,
    PositionManagementExecutionPublicError,
    PositionManagementExecutionUnavailable,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.shared.decimal_text import is_positive_exact_decimal_text
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue, freeze_json

_PROTECTION_SUCCESS_FIELDS = frozenset(
    {"strategy_instance_id", "trade_cycle_id", "status", "stop_price", "take_price"}
)
_CLOSE_SUCCESS_FIELDS = frozenset({"strategy_instance_id", "trade_cycle_id", "status"})
_ERROR_ENVELOPE_FIELDS = frozenset({"error"})
_ERROR_FIELDS_WITHOUT_DETAILS = frozenset({"code", "message"})
_ERROR_FIELDS_WITH_DETAILS = frozenset({"code", "message", "details"})
_VALIDATION_DETAIL_FIELDS = frozenset({"path", "message"})
_INTERNAL_ERROR_CODE = "internal_error"

_APPLY_PROTECTION_PUBLIC_CODES = {
    400: frozenset({"malformed_json"}),
    415: frozenset({"unsupported_media_type"}),
    422: frozenset(
        {
            "validation_failed",
            "unknown_trade_cycle_binding",
            "unsupported_exchange_scope",
            "position_not_open",
        }
    ),
}
_CLOSE_POSITION_PUBLIC_CODES = {
    422: frozenset(
        {"validation_failed", "unknown_trade_cycle_binding", "unsupported_exchange_scope"}
    ),
}


def decode_apply_protection_response(
    *, status_code: int, content_type: str | None, content: bytes, command: ApplyProtectionCommand
) -> ProtectionAppliedConfirmation:
    """Decode one `apply_protection` response or fail closed with a typed failure."""
    payload = _load_payload(content_type, content)

    if status_code == 200:
        return _decode_protection_success(payload, command)
    if status_code == 500:
        _decode_internal_error_envelope(payload)
        raise PositionManagementExecutionUnavailable(
            "ABI position-management unavailable: HTTP 500"
        )
    if status_code in _APPLY_PROTECTION_PUBLIC_CODES:
        _raise_public_error(status_code, payload, _APPLY_PROTECTION_PUBLIC_CODES[status_code])
    raise PositionManagementExecutionProtocolError(
        f"undocumented ABI apply_protection HTTP status: {status_code}"
    )


def decode_close_position_response(
    *, status_code: int, content_type: str | None, content: bytes, command: ClosePositionCommand
) -> PositionClosedConfirmation:
    """Decode one `close_position` response or fail closed with a typed failure."""
    payload = _load_payload(content_type, content)

    if status_code == 200:
        return _decode_close_success(payload, command)
    if status_code == 500:
        _decode_internal_error_envelope(payload)
        raise PositionManagementExecutionUnavailable(
            "ABI position-management unavailable: HTTP 500"
        )
    if status_code in _CLOSE_POSITION_PUBLIC_CODES:
        _raise_public_error(status_code, payload, _CLOSE_POSITION_PUBLIC_CODES[status_code])
    raise PositionManagementExecutionProtocolError(
        f"undocumented ABI close_position HTTP status: {status_code}"
    )


def _load_payload(content_type: str | None, content: bytes) -> object:
    _require_json_content_type(content_type)
    return _load_strict_json(content)


def _decode_protection_success(
    payload: object, command: ApplyProtectionCommand
) -> ProtectionAppliedConfirmation:
    try:
        body = _closed_object(payload, _PROTECTION_SUCCESS_FIELDS, "success response")
        if body["status"] != "protection_applied":
            raise ValueError("success status is not protection_applied")
        strategy_instance_id = _non_empty_string(
            body["strategy_instance_id"], "strategy_instance_id"
        )
        trade_cycle_id = _non_empty_string(body["trade_cycle_id"], "trade_cycle_id")
        stop_price = _positive_exact_decimal_string(body["stop_price"], "stop_price")
        take_price = _optional_positive_exact_decimal_string(body["take_price"], "take_price")
    except (KeyError, TypeError, ValueError) as exc:
        raise PositionManagementExecutionProtocolError(
            f"invalid ABI protection success response: {exc}"
        ) from exc

    if (
        strategy_instance_id != command.strategy_instance_id
        or trade_cycle_id != command.trade_cycle_id
        or stop_price != command.desired_protection.stop_price
        or take_price != command.desired_protection.take_price
    ):
        raise PositionManagementExecutionProtocolError(
            "ABI protection success response does not match the sent command"
        )
    return ProtectionAppliedConfirmation(
        strategy_instance_id=strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        confirmed_protection=DesiredProtection(stop_price=stop_price, take_price=take_price),
    )


def _decode_close_success(
    payload: object, command: ClosePositionCommand
) -> PositionClosedConfirmation:
    try:
        body = _closed_object(payload, _CLOSE_SUCCESS_FIELDS, "success response")
        if body["status"] != "trade_cycle_closed":
            raise ValueError("success status is not trade_cycle_closed")
        confirmation = PositionClosedConfirmation(
            strategy_instance_id=_non_empty_string(
                body["strategy_instance_id"], "strategy_instance_id"
            ),
            trade_cycle_id=_non_empty_string(body["trade_cycle_id"], "trade_cycle_id"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PositionManagementExecutionProtocolError(
            f"invalid ABI close success response: {exc}"
        ) from exc

    if (
        confirmation.strategy_instance_id != command.strategy_instance_id
        or confirmation.trade_cycle_id != command.trade_cycle_id
    ):
        raise PositionManagementExecutionProtocolError(
            "ABI close success response does not match the sent command"
        )
    return confirmation


def _raise_public_error(
    status_code: int, payload: object, allowed_codes: frozenset[str]
) -> NoReturn:
    try:
        envelope = _closed_object(payload, _ERROR_ENVELOPE_FIELDS, "error envelope")
        error = _closed_object(envelope["error"], None, "error object")
        code = _non_empty_string(error.get("code"), "error.code")
        if code not in allowed_codes:
            raise ValueError(f"undocumented error code for HTTP {status_code}: {code!r}")

        if code == "validation_failed":
            _require_exact_fields(error, _ERROR_FIELDS_WITH_DETAILS, "error")
            message = _non_empty_string(error["message"], "error.message")
            details: FrozenJsonValue | None = _decode_validation_details(error["details"])
        else:
            _require_exact_fields(error, _ERROR_FIELDS_WITHOUT_DETAILS, "error")
            message = _non_empty_string(error["message"], "error.message")
            details = None
    except (KeyError, TypeError, ValueError) as exc:
        raise PositionManagementExecutionProtocolError(
            f"invalid ABI position-management error envelope: {exc}"
        ) from exc

    raise PositionManagementExecutionPublicError(
        status_code=status_code, code=code, message=message, details=details
    )


def _decode_validation_details(value: object) -> FrozenJsonValue:
    if type(value) is not list or len(value) == 0:
        raise ValueError("error.details must be a non-empty array")
    items = cast("list[object]", value)
    for item in items:
        detail = _closed_object(item, _VALIDATION_DETAIL_FIELDS, "error.details item")
        _string(detail["path"], "error.details[].path")
        _string(detail["message"], "error.details[].message")
    return freeze_json(items)


def _decode_internal_error_envelope(payload: object) -> None:
    try:
        envelope = _closed_object(payload, _ERROR_ENVELOPE_FIELDS, "error envelope")
        error = _closed_object(envelope["error"], _ERROR_FIELDS_WITHOUT_DETAILS, "error")
        code = _non_empty_string(error["code"], "error.code")
        if code != _INTERNAL_ERROR_CODE:
            raise ValueError(f"undocumented 500 error code: {code!r}")
        _non_empty_string(error["message"], "error.message")
    except (KeyError, TypeError, ValueError) as exc:
        raise PositionManagementExecutionProtocolError(
            f"invalid ABI position-management error envelope: {exc}"
        ) from exc


def _load_strict_json(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_fields,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PositionManagementExecutionProtocolError(
            f"invalid ABI position-management JSON response: {exc}"
        ) from exc


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
        raise PositionManagementExecutionProtocolError(
            "ABI position-management response is missing content-type"
        )
    parts = value.split(";")
    if parts[0].strip().lower() != "application/json":
        raise PositionManagementExecutionProtocolError(
            "ABI position-management response content-type is not application/json"
        )

    seen_charset = False
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or "=" not in parameter:
            raise PositionManagementExecutionProtocolError(
                "ABI position-management response content-type is malformed"
            )
        name, raw_value = parameter.split("=", 1)
        if name.strip().lower() != "charset" or seen_charset:
            raise PositionManagementExecutionProtocolError(
                "ABI position-management response content-type has unsupported parameters"
            )
        charset = raw_value.strip()
        if len(charset) >= 2 and charset[0] == charset[-1] == '"':
            charset = charset[1:-1]
        if charset.lower() != "utf-8":
            raise PositionManagementExecutionProtocolError(
                "ABI position-management response charset is not UTF-8"
            )
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


def _positive_exact_decimal_string(value: object, name: str) -> str:
    text = _string(value, name)
    if not is_positive_exact_decimal_text(text):
        raise ValueError(f"{name} must be positive exact-decimal text")
    return text


def _optional_positive_exact_decimal_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _positive_exact_decimal_string(value, name)


def _non_empty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if len(result) == 0:
        raise ValueError(f"{name} must be non-empty")
    return result
