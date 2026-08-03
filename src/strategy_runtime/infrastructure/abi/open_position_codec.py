"""Strict JSON codec for the ABI open-position lookup HTTP contract."""

import json
from typing import NoReturn, cast

from strategy_runtime.runtime.open_position.errors import (
    OpenPositionLookupProtocolError,
    OpenPositionLookupPublicError,
    OpenPositionLookupUnavailable,
)
from strategy_runtime.runtime.open_position.models import OpenPositionLookupResponse
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue, freeze_json

_SUCCESS_FIELDS = frozenset({"position_open", "first_fill_at_ms", "average_entry_price"})
_VALIDATION_DETAIL_FIELDS = frozenset({"path", "message"})
_ERROR_ENVELOPE_FIELDS = frozenset({"error"})
_ERROR_OBJECT_FIELDS_WITHOUT_DETAILS = frozenset({"code", "message"})
_ERROR_OBJECT_FIELDS_WITH_DETAILS = frozenset({"code", "message", "details"})
_NO_DETAILS_PUBLIC_CODES = frozenset({"unknown_trade_cycle_binding", "unsupported_exchange_scope"})
_INTERNAL_ERROR_CODE = "internal_error"


def decode_open_position_response(
    *, status_code: int, content_type: str | None, content: bytes
) -> OpenPositionLookupResponse:
    """Decode one response or fail closed with a typed ABI failure."""
    _require_json_content_type(content_type)
    payload = _load_strict_json(content)

    if status_code == 200:
        return _decode_success(payload)
    if status_code == 422:
        code, message, details = _decode_public_error_envelope(payload)
        raise OpenPositionLookupPublicError(
            status_code=status_code, code=code, message=message, details=details
        )
    if status_code == 500:
        _decode_internal_error_envelope(payload)
        raise OpenPositionLookupUnavailable("ABI open-position lookup unavailable: HTTP 500")
    raise OpenPositionLookupProtocolError(f"undocumented ABI HTTP status: {status_code}")


def _decode_success(payload: object) -> OpenPositionLookupResponse:
    try:
        body = _closed_object(payload, _SUCCESS_FIELDS, "success response")
        position_open = body["position_open"]
        if type(position_open) is not bool:
            raise TypeError("position_open must be a boolean")

        first_fill_payload = body["first_fill_at_ms"]
        first_fill_at_ms: int | None
        if first_fill_payload is None:
            first_fill_at_ms = None
        elif type(first_fill_payload) is int:
            first_fill_at_ms = first_fill_payload
        else:
            raise TypeError("first_fill_at_ms must be a JSON integer or null")

        average_price_payload = body["average_entry_price"]
        average_entry_price = (
            None
            if average_price_payload is None
            else _string(average_price_payload, "average_entry_price")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenPositionLookupProtocolError(
            f"invalid ABI open-position success response: {exc}"
        ) from exc

    try:
        return OpenPositionLookupResponse(
            position_open=position_open,
            first_fill_at_ms=first_fill_at_ms,
            average_entry_price=average_entry_price,
        )
    except (TypeError, ValueError) as exc:
        raise OpenPositionLookupProtocolError(
            f"invalid ABI open-position success response: {exc}"
        ) from exc


def _decode_public_error_envelope(payload: object) -> tuple[str, str, FrozenJsonValue | None]:
    try:
        envelope = _closed_object(payload, _ERROR_ENVELOPE_FIELDS, "error envelope")
        error = envelope["error"]
        if type(error) is not dict:
            raise TypeError("error must be a JSON object")
        error_object = cast("dict[str, object]", error)
        code = _non_empty_string(error_object.get("code"), "error.code")

        if code == "validation_failed":
            fields = _closed_object(error_object, _ERROR_OBJECT_FIELDS_WITH_DETAILS, "error")
            message = _non_empty_string(fields["message"], "error.message")
            details = _decode_validation_details(fields["details"])
            return code, message, details

        if code in _NO_DETAILS_PUBLIC_CODES:
            fields = _closed_object(error_object, _ERROR_OBJECT_FIELDS_WITHOUT_DETAILS, "error")
            message = _non_empty_string(fields["message"], "error.message")
            return code, message, None

        raise ValueError(f"undocumented open-position error code: {code!r}")
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenPositionLookupProtocolError(
            f"invalid ABI open-position error envelope: {exc}"
        ) from exc


def _decode_validation_details(value: object) -> FrozenJsonValue:
    if type(value) is not list or len(value) == 0:
        raise ValueError("error.details must be a non-empty array")
    items = cast("list[object]", value)
    for item in items:
        detail = _closed_object(item, _VALIDATION_DETAIL_FIELDS, "error.details item")
        _non_empty_string(detail["path"], "error.details[].path")
        _non_empty_string(detail["message"], "error.details[].message")
    frozen = freeze_json(items)
    return frozen


def _decode_internal_error_envelope(payload: object) -> None:
    try:
        envelope = _closed_object(payload, _ERROR_ENVELOPE_FIELDS, "error envelope")
        error = envelope["error"]
        if type(error) is not dict:
            raise TypeError("error must be a JSON object")
        error_object = cast("dict[str, object]", error)
        fields = _closed_object(error_object, _ERROR_OBJECT_FIELDS_WITHOUT_DETAILS, "error")
        code = _non_empty_string(fields["code"], "error.code")
        if code != _INTERNAL_ERROR_CODE:
            raise ValueError(f"undocumented 500 error code: {code!r}")
        _non_empty_string(fields["message"], "error.message")
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenPositionLookupProtocolError(
            f"invalid ABI open-position error envelope: {exc}"
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
        raise OpenPositionLookupProtocolError(
            f"invalid ABI open-position JSON response: {exc}"
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
        raise OpenPositionLookupProtocolError("ABI open-position response is missing content-type")
    parts = value.split(";")
    if parts[0].strip().lower() != "application/json":
        raise OpenPositionLookupProtocolError(
            "ABI open-position response content-type is not application/json"
        )

    seen_charset = False
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or "=" not in parameter:
            raise OpenPositionLookupProtocolError(
                "ABI open-position response content-type is malformed"
            )
        name, raw_value = parameter.split("=", 1)
        if name.strip().lower() != "charset" or seen_charset:
            raise OpenPositionLookupProtocolError(
                "ABI open-position response content-type has unsupported parameters"
            )
        charset = raw_value.strip()
        if len(charset) >= 2 and charset[0] == charset[-1] == '"':
            charset = charset[1:-1]
        if charset.lower() != "utf-8":
            raise OpenPositionLookupProtocolError("ABI open-position response charset is not UTF-8")
        seen_charset = True


def _closed_object(value: object, fields: frozenset[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be a JSON object")
    result = cast("dict[str, object]", value)
    actual = frozenset(result)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise ValueError(f"{name} fields differ; missing={missing}, unknown={unknown}")
    return result


def _string(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    return value


def _non_empty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if len(result) == 0:
        raise ValueError(f"{name} must be non-empty")
    return result
