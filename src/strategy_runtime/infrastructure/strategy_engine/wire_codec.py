"""Strict JSON codec for the Strategy Engine live-entry/open-trade HTTP contract."""

import json
from collections.abc import Mapping, Sequence
from typing import Literal, NoReturn, cast

from strategy_runtime.runtime.engine.errors import (
    StrategyEngineMarketStreamNotFound,
    StrategyEngineProjectionProtocolError,
    StrategyEngineProjectionPublicError,
)
from strategy_runtime.runtime.engine.live_entry import (
    LiveEntryProjectionRequest,
    LiveEntryProjectionResponse,
)
from strategy_runtime.runtime.engine.open_trade import (
    OpenTradeProjectionRequest,
    OpenTradeProjectionResponse,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue, freeze_json

_DOCUMENTED_ENGINE_ERROR_STATUSES = frozenset({404, 409, 422, 500, 501, 502, 503})
_ERROR_ENVELOPE_FIELDS = frozenset({"error", "message", "details", "request_id"})

_LIVE_ENTRY_SUCCESS_FIELDS = frozenset({"desired_entry"})
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

_OPEN_TRADE_SUCCESS_FIELDS = frozenset({"desired_protection", "close_signal", "diagnostics"})
_EXECUTED_TRADE_RECEIPT_FIELDS = frozenset(
    {
        "side",
        "source_plan_bar_open_time_ms",
        "entry_bar_open_time_ms",
        "planned_entry_price",
        "initial_stop_price",
        "initial_take_price",
        "locked_exit_profile",
    }
)
_DESIRED_PROTECTION_FIELDS = frozenset({"stop_price", "take_price"})
_CLOSE_SIGNAL_FIELDS = frozenset({"active", "reason", "component_id", "layer"})


def encode_live_entry_request(request: LiveEntryProjectionRequest) -> dict[str, object]:
    """Create the exact five-field Engine live-entry request body."""
    _validate_live_entry_request(request)
    return {
        "strategy_id": request.strategy_id,
        "raw_spec": _unfreeze_json(request.raw_spec),
        "ticker": request.ticker,
        "base_timeframe": request.base_timeframe,
        "target_bar_open_time_ms": request.target_bar_open_time_ms,
    }


def _validate_live_entry_request(request: LiveEntryProjectionRequest) -> None:
    if type(request) is not LiveEntryProjectionRequest:
        raise TypeError("request must be LiveEntryProjectionRequest")
    _require_request_string(request.strategy_id, "strategy_id")
    _require_request_string(request.ticker, "ticker")
    _require_request_string(request.base_timeframe, "base_timeframe")
    _require_json_object_mapping(request.raw_spec, "raw_spec")
    _require_exact_int(request.target_bar_open_time_ms, "target_bar_open_time_ms")


def decode_live_entry_response(
    *, status_code: int, content_type: str | None, content: bytes
) -> LiveEntryProjectionResponse:
    """Decode one live-entry response or fail closed with a typed Engine failure."""
    _require_json_content_type(content_type)
    payload = _load_strict_json(content)

    if status_code == 200:
        return _decode_live_entry_success(payload)
    if status_code in _DOCUMENTED_ENGINE_ERROR_STATUSES:
        _raise_engine_public_error(status_code, payload)
    raise StrategyEngineProjectionProtocolError(f"undocumented Engine HTTP status: {status_code}")


def encode_open_trade_request(request: OpenTradeProjectionRequest) -> dict[str, object]:
    """Create the exact six-field Engine open-trade request body."""
    _validate_open_trade_request(request)
    entry = request.desired_entry
    return {
        "strategy_id": request.strategy_id,
        "raw_spec": _unfreeze_json(request.raw_spec),
        "ticker": request.ticker,
        "base_timeframe": request.base_timeframe,
        "target_bar_open_time_ms": request.target_bar_open_time_ms,
        "executed_trade_receipt": {
            "side": entry.side,
            "source_plan_bar_open_time_ms": entry.source_plan_bar_open_time_ms,
            "entry_bar_open_time_ms": request.entry_bar_open_time_ms,
            "planned_entry_price": entry.planned_entry_price,
            "initial_stop_price": entry.initial_stop_price,
            "initial_take_price": entry.initial_take_price,
            "locked_exit_profile": entry.locked_exit_profile,
        },
    }


def _validate_open_trade_request(request: OpenTradeProjectionRequest) -> None:
    if type(request) is not OpenTradeProjectionRequest:
        raise TypeError("request must be OpenTradeProjectionRequest")
    _require_request_string(request.strategy_id, "strategy_id")
    _require_request_string(request.ticker, "ticker")
    _require_request_string(request.base_timeframe, "base_timeframe")
    _require_json_object_mapping(request.raw_spec, "raw_spec")
    _require_exact_int(request.target_bar_open_time_ms, "target_bar_open_time_ms")
    _require_exact_int(request.entry_bar_open_time_ms, "entry_bar_open_time_ms")
    if type(request.desired_entry) is not DesiredEntry:
        raise TypeError("desired_entry must be DesiredEntry")


def decode_open_trade_response(
    *, status_code: int, content_type: str | None, content: bytes
) -> OpenTradeProjectionResponse:
    """Decode one open-trade response or fail closed with a typed Engine failure."""
    _require_json_content_type(content_type)
    payload = _load_strict_json(content)

    if status_code == 200:
        return _decode_open_trade_success(payload)
    if status_code in _DOCUMENTED_ENGINE_ERROR_STATUSES:
        _raise_engine_public_error(status_code, payload)
    raise StrategyEngineProjectionProtocolError(f"undocumented Engine HTTP status: {status_code}")


def _decode_live_entry_success(payload: object) -> LiveEntryProjectionResponse:
    try:
        body = _closed_object(payload, _LIVE_ENTRY_SUCCESS_FIELDS, "live-entry success response")
        desired_entry_payload = body["desired_entry"]
        desired_entry = (
            None
            if desired_entry_payload is None
            else _decode_wire_desired_entry(desired_entry_payload)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StrategyEngineProjectionProtocolError(
            f"invalid live-entry success response: {exc}"
        ) from exc
    return LiveEntryProjectionResponse(desired_entry=desired_entry)


def _decode_wire_desired_entry(payload: object) -> DesiredEntry:
    body = _closed_object(payload, _DESIRED_ENTRY_FIELDS, "desired_entry")
    side = body["side"]
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    source_open_time = body["source_plan_bar_open_time_ms"]
    if type(source_open_time) is not int:
        raise TypeError("source_plan_bar_open_time_ms must be a JSON integer")
    return DesiredEntry(
        side=cast("Literal['long', 'short']", side),
        source_plan_bar_open_time_ms=source_open_time,
        planned_entry_price=_string(body["planned_entry_price"], "planned_entry_price"),
        initial_stop_price=_string(body["initial_stop_price"], "initial_stop_price"),
        initial_take_price=_string(body["initial_take_price"], "initial_take_price"),
        locked_exit_profile=_string(body["locked_exit_profile"], "locked_exit_profile"),
    )


def _decode_open_trade_success(payload: object) -> OpenTradeProjectionResponse:
    try:
        body = _closed_object(payload, _OPEN_TRADE_SUCCESS_FIELDS, "open-trade success response")
        protection = _decode_desired_protection(body["desired_protection"])
        close_signal = _decode_close_signal(body["close_signal"])
        diagnostics_payload = _json_object(body["diagnostics"], "diagnostics")
    except (KeyError, TypeError, ValueError) as exc:
        raise StrategyEngineProjectionProtocolError(
            f"invalid open-trade success response: {exc}"
        ) from exc

    frozen_diagnostics = freeze_json(diagnostics_payload)
    if not isinstance(frozen_diagnostics, Mapping):
        raise StrategyEngineProjectionProtocolError("diagnostics must be a JSON object")

    return OpenTradeProjectionResponse(
        desired_protection=protection,
        close_signal=close_signal,
        diagnostics=frozen_diagnostics,
    )


def _decode_desired_protection(payload: object) -> DesiredProtection:
    body = _closed_object(payload, _DESIRED_PROTECTION_FIELDS, "desired_protection")
    stop_price = _string(body["stop_price"], "stop_price")
    take_price_payload = body["take_price"]
    take_price = None if take_price_payload is None else _string(take_price_payload, "take_price")
    return DesiredProtection(stop_price=stop_price, take_price=take_price)


def _decode_close_signal(payload: object) -> CloseSignal:
    body = _closed_object(payload, _CLOSE_SIGNAL_FIELDS, "close_signal")
    active = body["active"]
    if type(active) is not bool:
        raise TypeError("active must be a boolean")
    return CloseSignal(
        active=active,
        reason=_optional_string(body["reason"], "reason"),
        component_id=_optional_string(body["component_id"], "component_id"),
        layer=_optional_string(body["layer"], "layer"),
    )


def _raise_engine_public_error(status_code: int, payload: object) -> NoReturn:
    try:
        envelope = _closed_object(payload, _ERROR_ENVELOPE_FIELDS, "error envelope")
        code = _non_empty_string(envelope["error"], "error")
        message = _non_empty_string(envelope["message"], "message")
        details_payload = _json_object(envelope["details"], "details")
        request_id = _non_empty_string(envelope["request_id"], "request_id")
    except (KeyError, TypeError, ValueError) as exc:
        raise StrategyEngineProjectionProtocolError(
            f"invalid Engine error envelope: {exc}"
        ) from exc

    frozen_details = freeze_json(details_payload)
    if not isinstance(frozen_details, Mapping):
        raise StrategyEngineProjectionProtocolError(
            "Engine error envelope details must be an object"
        )

    if status_code == 404 and code == "market_stream_not_found":
        raise StrategyEngineMarketStreamNotFound(
            status_code=status_code,
            code=code,
            message=message,
            details=frozen_details,
            request_id=request_id,
        )
    raise StrategyEngineProjectionPublicError(
        status_code=status_code,
        code=code,
        message=message,
        details=frozen_details,
        request_id=request_id,
    )


def _require_request_string(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")


def _require_json_object_mapping(value: object, name: str) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object mapping")


def _require_exact_int(value: object, name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be a JSON integer, not a boolean")


def _unfreeze_json(value: FrozenJsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _unfreeze_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_unfreeze_json(item) for item in value]
    return value


def _load_strict_json(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_fields,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StrategyEngineProjectionProtocolError(f"invalid Engine JSON response: {exc}") from exc


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
        raise StrategyEngineProjectionProtocolError("Engine response is missing content-type")
    parts = value.split(";")
    if parts[0].strip().lower() != "application/json":
        raise StrategyEngineProjectionProtocolError(
            "Engine response content-type is not application/json"
        )

    seen_charset = False
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or "=" not in parameter:
            raise StrategyEngineProjectionProtocolError("Engine response content-type is malformed")
        name, raw_value = parameter.split("=", 1)
        if name.strip().lower() != "charset" or seen_charset:
            raise StrategyEngineProjectionProtocolError(
                "Engine response content-type has unsupported parameters"
            )
        charset = raw_value.strip()
        if len(charset) >= 2 and charset[0] == charset[-1] == '"':
            charset = charset[1:-1]
        if charset.lower() != "utf-8":
            raise StrategyEngineProjectionProtocolError("Engine response charset is not UTF-8")
        seen_charset = True


def _closed_object(value: object, fields: frozenset[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be a JSON object")
    result = cast("dict[str, object]", value)
    _require_exact_fields(result, fields, name)
    return result


def _json_object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be a JSON object")
    return cast("dict[str, object]", value)


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


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _non_empty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if len(result) == 0:
        raise ValueError(f"{name} must be non-empty")
    return result
