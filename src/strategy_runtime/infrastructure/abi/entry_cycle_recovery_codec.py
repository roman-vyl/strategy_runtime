"""Strict JSON codec for the ABI entry-cycle recovery-state HTTP contract."""

import json
from typing import Literal, NoReturn, cast

from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryProtocolError,
    AbiEntryCycleRecoveryUnavailable,
    AbiEntryCycleRecoveryUnknownTradeCycleBinding,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import (
    EntryOrderLiveRecoveryState,
    PositionOpenRecoveryState,
    RecoveryStateAppliedEntryPackage,
    RecoveryStateResponse,
    TerminalAfterFillRecoveryState,
    TerminalWithoutFillRecoveryState,
)
from strategy_runtime.runtime.abi.entry_package_models import EntryPackageWireDesiredEntry

_SUCCESS_FIELDS = frozenset(
    {"recovery_state", "applied_entry_package", "first_fill_at_ms", "average_entry_price"}
)
_APPLIED_ENTRY_PACKAGE_FIELDS = frozenset({"applied_desired_entry", "calculated_quantity"})
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
_ERROR_ENVELOPE_FIELDS = frozenset({"error"})
_ERROR_OBJECT_FIELDS = frozenset({"code", "message"})
_UNKNOWN_BINDING_CODE = "unknown_trade_cycle_binding"
_INTERNAL_ERROR_CODE = "internal_error"
_TERMINAL_STATES = frozenset({"terminal_without_fill", "terminal_after_fill"})


def decode_recovery_state_response(
    *, status_code: int, content_type: str | None, content: bytes
) -> RecoveryStateResponse:
    """Decode one response or fail closed with a typed ABI failure."""
    _require_json_content_type(content_type)
    payload = _load_strict_json(content)

    if status_code == 200:
        return _decode_success(payload)
    if status_code == 422:
        message = _decode_error_envelope(payload, expected_code=_UNKNOWN_BINDING_CODE)
        raise AbiEntryCycleRecoveryUnknownTradeCycleBinding(message)
    if status_code == 500:
        _decode_error_envelope(payload, expected_code=_INTERNAL_ERROR_CODE)
        raise AbiEntryCycleRecoveryUnavailable(
            "ABI entry-cycle recovery-state unavailable: HTTP 500"
        )
    raise AbiEntryCycleRecoveryProtocolError(f"undocumented ABI HTTP status: {status_code}")


def _decode_success(payload: object) -> RecoveryStateResponse:
    try:
        body = _closed_object(payload, _SUCCESS_FIELDS, "success response")
        recovery_state = body["recovery_state"]
        applied_payload = body["applied_entry_package"]
        first_fill_payload = body["first_fill_at_ms"]
        average_price_payload = body["average_entry_price"]

        if recovery_state == "entry_order_live":
            _require_none(first_fill_payload, "first_fill_at_ms")
            _require_none(average_price_payload, "average_entry_price")
            return EntryOrderLiveRecoveryState(
                applied_entry_package=_decode_applied_entry_package(applied_payload)
            )

        if recovery_state == "position_open":
            return PositionOpenRecoveryState(
                applied_entry_package=_decode_applied_entry_package(applied_payload),
                first_fill_at_ms=_int(first_fill_payload, "first_fill_at_ms"),
                average_entry_price=_string(average_price_payload, "average_entry_price"),
            )

        if recovery_state in _TERMINAL_STATES:
            _require_none(applied_payload, "applied_entry_package")
            _require_none(first_fill_payload, "first_fill_at_ms")
            _require_none(average_price_payload, "average_entry_price")
            if recovery_state == "terminal_without_fill":
                return TerminalWithoutFillRecoveryState()
            return TerminalAfterFillRecoveryState()

        raise ValueError(f"undocumented recovery_state: {recovery_state!r}")
    except (KeyError, TypeError, ValueError) as exc:
        raise AbiEntryCycleRecoveryProtocolError(
            f"invalid ABI recovery-state success response: {exc}"
        ) from exc


def _decode_applied_entry_package(payload: object) -> RecoveryStateAppliedEntryPackage:
    body = _closed_object(payload, _APPLIED_ENTRY_PACKAGE_FIELDS, "applied_entry_package")
    return RecoveryStateAppliedEntryPackage(
        applied_desired_entry=_decode_desired_entry(body["applied_desired_entry"]),
        calculated_quantity=_string(body["calculated_quantity"], "calculated_quantity"),
    )


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


def _decode_error_envelope(payload: object, *, expected_code: str) -> str:
    try:
        envelope = _closed_object(payload, _ERROR_ENVELOPE_FIELDS, "error envelope")
        error = _closed_object(envelope["error"], _ERROR_OBJECT_FIELDS, "error object")
        code = _non_empty_string(error["code"], "error.code")
        if code != expected_code:
            raise ValueError(f"expected error code {expected_code!r}, got {code!r}")
        return _non_empty_string(error["message"], "error.message")
    except (KeyError, TypeError, ValueError) as exc:
        raise AbiEntryCycleRecoveryProtocolError(
            f"invalid ABI entry-cycle recovery-state error envelope: {exc}"
        ) from exc


def _require_none(value: object, name: str) -> None:
    if value is not None:
        raise ValueError(f"{name} must be null for this recovery_state")


def _load_strict_json(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_fields,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AbiEntryCycleRecoveryProtocolError(
            f"invalid ABI entry-cycle recovery-state JSON response: {exc}"
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
        raise AbiEntryCycleRecoveryProtocolError(
            "ABI entry-cycle recovery-state response is missing content-type"
        )
    parts = value.split(";")
    if parts[0].strip().lower() != "application/json":
        raise AbiEntryCycleRecoveryProtocolError(
            "ABI entry-cycle recovery-state response content-type is not application/json"
        )

    seen_charset = False
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or "=" not in parameter:
            raise AbiEntryCycleRecoveryProtocolError(
                "ABI entry-cycle recovery-state response content-type is malformed"
            )
        name, raw_value = parameter.split("=", 1)
        if name.strip().lower() != "charset" or seen_charset:
            raise AbiEntryCycleRecoveryProtocolError(
                "ABI entry-cycle recovery-state response content-type has unsupported parameters"
            )
        charset = raw_value.strip()
        if len(charset) >= 2 and charset[0] == charset[-1] == '"':
            charset = charset[1:-1]
        if charset.lower() != "utf-8":
            raise AbiEntryCycleRecoveryProtocolError(
                "ABI entry-cycle recovery-state response charset is not UTF-8"
            )
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


def _int(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be a JSON integer")
    return value


def _string(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    return value


def _non_empty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if len(result) == 0:
        raise ValueError(f"{name} must be non-empty")
    return result
