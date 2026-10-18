"""`closure` decoding in the open-position and close codecs (runtime-trade-cycle-closure-v1)."""

import json

import pytest

from strategy_runtime.infrastructure.abi.open_position_codec import decode_open_position_response
from strategy_runtime.infrastructure.abi.position_management_codec import (
    decode_close_position_response,
)
from strategy_runtime.runtime.open_position.errors import OpenPositionLookupProtocolError
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionProtocolError,
)
from strategy_runtime.runtime.position_management_execution.models import ClosePositionCommand
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure

_SID = "ema_pullback:abc"
_CYCLE = "cycle-1"


def _stop_closure() -> dict[str, object]:
    return {
        "strategy_instance_id": _SID,
        "trade_cycle_id": _CYCLE,
        "reason": "stop_loss",
        "order_id": "a34add42",
        "order_link_id": None,
        "parent_order_link_id": "abi-ep-0ae6e4920f8d5c8568fa",
    }


def _lookup(body: dict[str, object]) -> object:
    return decode_open_position_response(
        status_code=200, content_type="application/json", content=json.dumps(body).encode()
    )


def _closed_body(**extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "position_open": False,
        "first_fill_at_ms": None,
        "average_entry_price": None,
        "closure": None,
        "entry_order_link_id": None,
        "entry_order_id": None,
    }
    body.update(extra)
    return body


def test_lookup_without_closure_key_is_rejected() -> None:
    body = _closed_body()
    del body["closure"]

    with pytest.raises(OpenPositionLookupProtocolError):
        _lookup(body)


def test_lookup_with_null_closure_means_no_closure() -> None:
    response = _lookup(_closed_body(closure=None))

    assert response.closure is None  # type: ignore[attr-defined]


def test_lookup_with_stop_loss_closure_carries_it_unchanged() -> None:
    response = _lookup(_closed_body(closure=_stop_closure()))

    assert response.closure == TradeCycleClosure(  # type: ignore[attr-defined]
        _SID, _CYCLE, "stop_loss", "a34add42", None, "abi-ep-0ae6e4920f8d5c8568fa"
    )


def test_lookup_rejects_closure_on_open_position() -> None:
    body = {
        "position_open": True,
        "first_fill_at_ms": 1,
        "average_entry_price": "81660.6",
        "closure": _stop_closure(),
        "entry_order_link_id": "abi-ep-link",
        "entry_order_id": None,
    }

    with pytest.raises(OpenPositionLookupProtocolError):
        _lookup(body)


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "manual"},
        {"order_id": ""},
        {"order_link_id": "close-1"},
        {"parent_order_link_id": None},
        {"extra": 1},
        {"order_id": 5},
    ],
)
def test_lookup_rejects_malformed_closure(change: dict[str, object]) -> None:
    closure = {**_stop_closure(), **change}

    with pytest.raises(OpenPositionLookupProtocolError):
        _lookup(_closed_body(closure=closure))


def test_lookup_rejects_runtime_signal_without_own_order_link_id() -> None:
    closure = {**_stop_closure(), "reason": "runtime_signal", "parent_order_link_id": None}

    with pytest.raises(OpenPositionLookupProtocolError):
        _lookup(_closed_body(closure=closure))


def test_lookup_still_rejects_unknown_success_fields() -> None:
    with pytest.raises(OpenPositionLookupProtocolError):
        _lookup(_closed_body(closure=None, executed_entry_price="1"))


def _close(body: dict[str, object]) -> object:
    return decode_close_position_response(
        status_code=200,
        content_type="application/json",
        content=json.dumps(body).encode(),
        command=ClosePositionCommand(_SID, _CYCLE),
    )


def _close_body(**extra: object) -> dict[str, object]:
    return {
        "strategy_instance_id": _SID,
        "trade_cycle_id": _CYCLE,
        "status": "trade_cycle_closed",
        **extra,
    }


def test_close_without_closure_key_decodes_as_before() -> None:
    assert _close(_close_body()).closure is None  # type: ignore[attr-defined]


def test_close_carries_a_stop_loss_closure_when_the_stop_beat_the_command() -> None:
    confirmation = _close(_close_body(closure=_stop_closure()))

    assert confirmation.closure.reason == "stop_loss"  # type: ignore[attr-defined]


def test_close_rejects_a_closure_for_another_cycle() -> None:
    closure = {**_stop_closure(), "trade_cycle_id": "cycle-2"}

    with pytest.raises(PositionManagementExecutionProtocolError):
        _close(_close_body(closure=closure))
