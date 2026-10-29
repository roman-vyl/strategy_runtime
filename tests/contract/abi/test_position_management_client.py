import json
from collections.abc import Callable

import httpx
import pytest

from strategy_runtime.infrastructure.abi.http_position_management import (
    HttpxAbiPositionManagementAdapter,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionNetworkFailure,
    PositionManagementExecutionProtocolError,
    PositionManagementExecutionPublicError,
    PositionManagementExecutionTimeout,
    PositionManagementExecutionUnavailable,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    EntryRemainderCancelConfirmation,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
    ProtectionOrder,
    ProtectionOrders,
)
from strategy_runtime.runtime.recipes.position_management import DesiredProtection

ResponseFactory = Callable[[httpx.Request], httpx.Response]


class FakeAbi:
    def __init__(self, response_factory: ResponseFactory) -> None:
        self.requests: list[httpx.Request] = []
        self._response_factory = response_factory
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response_factory(request)


# -- apply_protection: request shape ----------------------------------------


def test_apply_protection_sends_a_put_with_closed_body() -> None:
    fake = FakeAbi(lambda _: json_response(200, protection_applied_body()))

    result = apply_protection(fake, make_protection_command())

    assert result == ProtectionAppliedConfirmation(
        strategy_instance_id="instance-1",
        trade_cycle_id="cycle-1",
        confirmed_protection=DesiredProtection(stop_price="99000", take_price="103000"),
        protection_orders=ProtectionOrders(
            quantity="0.010",
            stop=ProtectionOrder(order_id="stop-order-1", trigger_price="99000.0"),
            take=ProtectionOrder(order_id="take-order-1", trigger_price="103000.0"),
        ),
    )
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "PUT"
    assert sent.url.raw_path == b"/v1/strategy-instances/instance-1/trade-cycles/cycle-1/protection"
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["accept"] == "application/json"
    assert json.loads(sent.content) == {"stop_price": "99000", "take_price": "103000"}


def test_apply_protection_with_null_take_price_is_sent_explicitly() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "strategy_instance_id": "instance-1",
                "trade_cycle_id": "cycle-1",
                "status": "protection_applied",
                "stop_price": "99000",
                "take_price": None,
                "protection_orders": protection_orders_body(take_trigger_price="990000"),
            },
        )
    )

    result = apply_protection(
        fake,
        make_protection_command(desired_protection=DesiredProtection("99000", None)),
    )

    assert result.confirmed_protection == DesiredProtection("99000", None)
    # No requested take, yet ABI's real (surrogate) take order is still carried.
    assert result.protection_orders.take == ProtectionOrder("take-order-1", "990000")
    assert json.loads(fake.requests[0].content) == {"stop_price": "99000", "take_price": None}


# -- close_position: request shape -------------------------------------------


def test_close_position_sends_a_post_with_canonical_exposure_fraction() -> None:
    fake = FakeAbi(lambda _: json_response(200, closed_body()))

    result = close_position(fake, make_close_command())

    assert result == PositionClosedConfirmation(
        strategy_instance_id="instance-1", trade_cycle_id="cycle-1"
    )
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "POST"
    assert sent.url.raw_path == b"/v1/strategy-instances/instance-1/trade-cycles/cycle-1/close"
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["accept"] == "application/json"
    assert json.loads(sent.content) == {"exposure_fraction": "1"}
    assert all(request.method != "DELETE" for request in fake.requests)


# -- opaque identifier encoding -----------------------------------------------


@pytest.mark.parametrize(
    ("strategy_instance_id", "expected_path"),
    [
        (
            "instance/future %",
            b"/v1/strategy-instances/instance%2Ffuture%20%25/trade-cycles/cycle/protection",
        ),
        (
            "цикл id",
            b"/v1/strategy-instances/%D1%86%D0%B8%D0%BA%D0%BB%20id/trade-cycles/cycle/protection",
        ),
        (".", b"/v1/strategy-instances/%2E/trade-cycles/cycle/protection"),
        ("..", b"/v1/strategy-instances/%2E%2E/trade-cycles/cycle/protection"),
    ],
)
def test_apply_protection_encodes_opaque_identifiers(
    strategy_instance_id: str, expected_path: bytes
) -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            protection_applied_body(
                strategy_instance_id=strategy_instance_id, trade_cycle_id="cycle"
            ),
        )
    )

    apply_protection(
        fake,
        make_protection_command(strategy_instance_id=strategy_instance_id, trade_cycle_id="cycle"),
    )

    assert fake.requests[0].url.raw_path == expected_path


@pytest.mark.parametrize(
    ("trade_cycle_id", "expected_path"),
    [
        (
            "cycle/future %",
            b"/v1/strategy-instances/instance/trade-cycles/cycle%2Ffuture%20%25/close",
        ),
        (".", b"/v1/strategy-instances/instance/trade-cycles/%2E/close"),
        ("..", b"/v1/strategy-instances/instance/trade-cycles/%2E%2E/close"),
    ],
)
def test_close_position_encodes_opaque_identifiers(
    trade_cycle_id: str, expected_path: bytes
) -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200, closed_body(strategy_instance_id="instance", trade_cycle_id=trade_cycle_id)
        )
    )

    close_position(
        fake, make_close_command(strategy_instance_id="instance", trade_cycle_id=trade_cycle_id)
    )

    assert fake.requests[0].url.raw_path == expected_path


# -- confirmation only on an exact match --------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"strategy_instance_id": "other-instance"}),
        lambda body: body.update({"trade_cycle_id": "other-cycle"}),
        lambda body: body.update({"stop_price": "1"}),
        lambda body: body.update({"take_price": "1"}),
    ],
)
def test_protection_response_mismatching_the_sent_command_fails_closed(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    body = protection_applied_body()
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"strategy_instance_id": "other-instance"}),
        lambda body: body.update({"trade_cycle_id": "other-cycle"}),
    ],
)
def test_close_response_mismatching_the_sent_command_fails_closed(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    body = closed_body()
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        close_position(fake, make_close_command())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"stop_price": "99000.0"}),
        lambda body: body.update({"stop_price": "99000e0"}),
        lambda body: body.update({"stop_price": "099000"}),
        lambda body: body.update({"take_price": "103000.00"}),
    ],
)
def test_protection_response_is_compared_as_raw_wire_text_not_normalized_value(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    """A numeric-equivalent but differently formatted wire value must not be
    silently normalized into a match: ABI is expected to echo back the exact
    accepted Runtime value, so any other formatting is a protocol
    contradiction."""
    body = protection_applied_body()
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"stop_price": "0"}),
        lambda body: body.update({"stop_price": "-99000"}),
        lambda body: body.update({"stop_price": "not-a-number"}),
        lambda body: body.update({"stop_price": ""}),
        lambda body: body.update({"take_price": "0"}),
        lambda body: body.update({"take_price": "-1"}),
    ],
)
def test_protection_response_rejects_non_positive_exact_decimal_wire_text(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    body = protection_applied_body()
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


# -- protection_orders: strict, carried, never compared ----------------------


def test_protection_response_without_protection_orders_is_rejected() -> None:
    body = protection_applied_body()
    del body["protection_orders"]
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


def _orders(body: dict[str, object]) -> dict[str, object]:
    return body["protection_orders"]  # type: ignore[return-value]


def _leg(body: dict[str, object], name: str) -> dict[str, object]:
    return _orders(body)[name]  # type: ignore[return-value]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"protection_orders": None}),
        lambda body: body.update({"protection_orders": []}),
        lambda body: body.update({"extra": 1}),
        lambda body: _orders(body).pop("quantity"),
        lambda body: _orders(body).pop("stop"),
        lambda body: _orders(body).pop("take"),
        lambda body: _orders(body).update({"extra": 1}),
        lambda body: _orders(body).update({"quantity": "0"}),
        lambda body: _orders(body).update({"quantity": "-0.01"}),
        lambda body: _orders(body).update({"quantity": "abc"}),
        lambda body: _orders(body).update({"quantity": 0.01}),
        lambda body: _orders(body).update({"take": None}),
        lambda body: _leg(body, "stop").pop("order_id"),
        lambda body: _leg(body, "stop").pop("trigger_price"),
        lambda body: _leg(body, "take").update({"order_link_id": ""}),
        lambda body: _leg(body, "stop").update({"order_id": ""}),
        lambda body: _leg(body, "take").update({"order_id": None}),
        lambda body: _leg(body, "take").update({"order_id": 7}),
        lambda body: _leg(body, "stop").update({"trigger_price": "0"}),
        lambda body: _leg(body, "stop").update({"trigger_price": "-1"}),
        lambda body: _leg(body, "take").update({"trigger_price": "1.2.3"}),
        lambda body: _leg(body, "take").update({"trigger_price": ""}),
        lambda body: _leg(body, "take").update({"trigger_price": 103000}),
    ],
)
def test_malformed_protection_orders_are_rejected(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    body = protection_applied_body()
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


def test_protection_orders_are_not_compared_with_the_command() -> None:
    body = protection_applied_body()
    body["protection_orders"] = {
        "quantity": "5",
        "stop": {"order_id": "s", "trigger_price": "1"},
        "take": {"order_id": "t", "trigger_price": "2"},
    }
    fake = FakeAbi(lambda _: json_response(200, body))

    result = apply_protection(fake, make_protection_command())

    assert result.protection_orders == ProtectionOrders(
        "5", ProtectionOrder("s", "1"), ProtectionOrder("t", "2")
    )


# -- documented public errors share one shape --------------------------------


@pytest.mark.parametrize(
    ("status_code", "code", "with_details"),
    [
        (400, "malformed_json", False),
        (415, "unsupported_media_type", False),
        (422, "validation_failed", True),
        (422, "unknown_trade_cycle_binding", False),
        (422, "unsupported_exchange_scope", False),
        (422, "position_not_open", False),
    ],
)
def test_apply_protection_documented_public_errors_share_one_type(
    status_code: int, code: str, with_details: bool
) -> None:
    error: dict[str, object] = {"code": code, "message": "rejected"}
    if with_details:
        error["details"] = [{"path": "/stop_price", "message": "bad"}]
    fake = FakeAbi(lambda _: json_response(status_code, {"error": error}))

    with pytest.raises(PositionManagementExecutionPublicError) as raised:
        apply_protection(fake, make_protection_command())

    caught = raised.value
    assert caught.status_code == status_code
    assert caught.code == code
    assert caught.message == "rejected"
    if with_details:
        assert list(caught.details) == [{"path": "/stop_price", "message": "bad"}]  # type: ignore[arg-type]
    else:
        assert caught.details is None


def test_validation_details_allow_empty_path_and_message() -> None:
    """The authoritative `ValidationDetail` schema declares `path`/`message`
    as plain strings with no `minLength` (unlike the envelope's own
    `error.message`, which does require `minLength: 1`) — exact decoding
    must not silently narrow the published contract."""
    error = {
        "code": "validation_failed",
        "message": "rejected",
        "details": [{"path": "", "message": ""}],
    }
    fake = FakeAbi(lambda _: json_response(422, {"error": error}))

    with pytest.raises(PositionManagementExecutionPublicError) as raised:
        apply_protection(fake, make_protection_command())

    assert list(raised.value.details) == [{"path": "", "message": ""}]  # type: ignore[arg-type]


def test_apply_protection_position_not_open_is_an_ordinary_public_error() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            422, {"error": {"code": "position_not_open", "message": "no live position"}}
        )
    )

    with pytest.raises(PositionManagementExecutionPublicError) as raised:
        apply_protection(fake, make_protection_command())

    assert raised.value.code == "position_not_open"
    assert not isinstance(raised.value, PositionManagementExecutionUnavailable)
    assert not isinstance(raised.value, PositionManagementExecutionProtocolError)


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (422, "validation_failed"),
        (422, "unknown_trade_cycle_binding"),
        (422, "unsupported_exchange_scope"),
        (422, "close_execution_incomplete"),
    ],
)
def test_close_position_documented_public_errors_share_one_type(
    status_code: int, code: str
) -> None:
    error: dict[str, object] = {"code": code, "message": "rejected"}
    if code == "validation_failed":
        error["details"] = [{"path": "/", "message": "request body must be empty"}]
    fake = FakeAbi(lambda _: json_response(status_code, {"error": error}))

    with pytest.raises(PositionManagementExecutionPublicError) as raised:
        close_position(fake, make_close_command())

    assert raised.value.status_code == status_code
    assert raised.value.code == code


def test_close_position_does_not_recognize_malformed_json_or_unsupported_media_type() -> None:
    fake = FakeAbi(
        lambda _: json_response(400, {"error": {"code": "malformed_json", "message": "bad"}})
    )

    with pytest.raises(PositionManagementExecutionProtocolError):
        close_position(fake, make_close_command())


def test_apply_protection_does_not_recognize_close_only_codes_at_other_statuses() -> None:
    fake = FakeAbi(
        lambda _: json_response(422, {"error": {"code": "made_up_business_code", "message": "bad"}})
    )

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


def test_close_position_does_not_recognize_position_not_open() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            422, {"error": {"code": "position_not_open", "message": "no live position"}}
        )
    )

    with pytest.raises(PositionManagementExecutionProtocolError):
        close_position(fake, make_close_command())


# -- internal_error is unavailable, not a public error ------------------------


@pytest.mark.parametrize("call", ["apply_protection", "close_position"])
def test_internal_error_is_unavailable_not_public_error(call: str) -> None:
    fake = FakeAbi(
        lambda _: json_response(500, {"error": {"code": "internal_error", "message": "boom"}})
    )

    with pytest.raises(PositionManagementExecutionUnavailable) as raised:
        if call == "apply_protection":
            apply_protection(fake, make_protection_command())
        else:
            close_position(fake, make_close_command())

    assert not isinstance(raised.value, PositionManagementExecutionPublicError)


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "not_internal_error", "message": "boom"}},
        {"error": {"code": "internal_error", "message": "boom", "details": {}}},
        {"error": "not an object"},
    ],
)
def test_500_outside_documented_internal_error_shape_fails_closed(body: object) -> None:
    fake = FakeAbi(lambda _: json_response(500, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())


# -- malformed/undocumented responses fail closed as one protocol class ------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"{", headers={"content-type": "application/json"}),
        httpx.Response(200, content=b"{}", headers={}),
        httpx.Response(
            200, content=b"{}", headers={"content-type": "application/json; charset=utf-16"}
        ),
        httpx.Response(403, json={"anything": True}, headers={"content-type": "application/json"}),
    ],
)
def test_malformed_or_undocumented_response_fails_closed(response: httpx.Response) -> None:
    fake = FakeAbi(lambda _: response)

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())

    assert len(fake.requests) == 1


def test_redirect_is_not_followed_and_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: httpx.Response(
            307,
            headers={"location": "http://other.test/target", "content-type": "application/json"},
            json=protection_applied_body(),
        )
    )

    with pytest.raises(PositionManagementExecutionProtocolError):
        apply_protection(fake, make_protection_command())

    assert len(fake.requests) == 1


# -- timeout and network failure ----------------------------------------------


@pytest.mark.parametrize("call", ["apply_protection", "close_position"])
def test_timeout_is_typed_and_not_retried(call: str) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fake = FakeAbi(timeout)

    with pytest.raises(PositionManagementExecutionTimeout):
        if call == "apply_protection":
            apply_protection(fake, make_protection_command())
        else:
            close_position(fake, make_close_command())

    assert len(fake.requests) == 1


@pytest.mark.parametrize("call", ["apply_protection", "close_position"])
def test_network_failure_is_typed_and_not_retried(call: str) -> None:
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    fake = FakeAbi(network_failure)

    with pytest.raises(PositionManagementExecutionNetworkFailure):
        if call == "apply_protection":
            apply_protection(fake, make_protection_command())
        else:
            close_position(fake, make_close_command())

    assert len(fake.requests) == 1


def test_every_transport_or_internal_failure_is_an_unavailable_subtype() -> None:
    assert issubclass(PositionManagementExecutionTimeout, PositionManagementExecutionUnavailable)
    assert issubclass(
        PositionManagementExecutionNetworkFailure, PositionManagementExecutionUnavailable
    )


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        HttpxAbiPositionManagementAdapter(
            base_url="http://abi.test",
            timeout_seconds=timeout_seconds,
            transport=httpx.MockTransport(lambda _: json_response(500, {})),
        )


# -- helpers -------------------------------------------------------------------


def apply_protection(
    fake: FakeAbi, command: ApplyProtectionCommand
) -> ProtectionAppliedConfirmation:
    with HttpxAbiPositionManagementAdapter(
        base_url="http://abi.test", timeout_seconds=0.25, transport=fake.transport
    ) as adapter:
        return adapter.apply_protection(command)


def close_position(fake: FakeAbi, command: ClosePositionCommand) -> PositionClosedConfirmation:
    with HttpxAbiPositionManagementAdapter(
        base_url="http://abi.test", timeout_seconds=0.25, transport=fake.transport
    ) as adapter:
        return adapter.close_position(command)


def make_protection_command(
    *,
    strategy_instance_id: str = "instance-1",
    trade_cycle_id: str = "cycle-1",
    desired_protection: DesiredProtection | None = None,
) -> ApplyProtectionCommand:
    return ApplyProtectionCommand(
        strategy_instance_id=strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        desired_protection=desired_protection or DesiredProtection("99000", "103000"),
    )


def make_close_command(
    *, strategy_instance_id: str = "instance-1", trade_cycle_id: str = "cycle-1"
) -> ClosePositionCommand:
    return ClosePositionCommand(
        strategy_instance_id=strategy_instance_id, trade_cycle_id=trade_cycle_id
    )


def protection_applied_body(
    *, strategy_instance_id: str = "instance-1", trade_cycle_id: str = "cycle-1"
) -> dict[str, object]:
    return {
        "strategy_instance_id": strategy_instance_id,
        "trade_cycle_id": trade_cycle_id,
        "status": "protection_applied",
        "stop_price": "99000",
        "take_price": "103000",
        "protection_orders": protection_orders_body(),
    }


def protection_orders_body(*, take_trigger_price: str = "103000.0") -> dict[str, object]:
    return {
        "quantity": "0.010",
        "stop": {"order_id": "stop-order-1", "trigger_price": "99000.0"},
        "take": {"order_id": "take-order-1", "trigger_price": take_trigger_price},
    }


def closed_body(
    *, strategy_instance_id: str = "instance-1", trade_cycle_id: str = "cycle-1"
) -> dict[str, object]:
    return {
        "strategy_instance_id": strategy_instance_id,
        "trade_cycle_id": trade_cycle_id,
        "status": "trade_cycle_closed",
    }


def json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"content-type": "application/json; charset=utf-8"},
    )


# -- cancel_entry_remainder (runtime-touch-trigger-remainder-cancel-v1) -------


def cancel_entry_remainder(
    fake: FakeAbi, strategy_instance_id: str = "instance-1", trade_cycle_id: str = "cycle-1"
) -> EntryRemainderCancelConfirmation:
    with HttpxAbiPositionManagementAdapter(
        base_url="http://abi.test", timeout_seconds=0.25, transport=fake.transport
    ) as adapter:
        return adapter.cancel_entry_remainder(strategy_instance_id, trade_cycle_id)


def remainder_body(
    *,
    trade_cycle_id: str = "cycle-1",
    status: str = "entry_remainder_cancelled",
    executed_quantity: object = "0.004",
) -> dict[str, object]:
    return {
        "strategy_instance_id": "instance-1",
        "trade_cycle_id": trade_cycle_id,
        "status": status,
        "executed_quantity": executed_quantity,
    }


def test_cancel_entry_remainder_sends_the_exact_narrow_request() -> None:
    fake = FakeAbi(lambda _: json_response(200, remainder_body()))

    result = cancel_entry_remainder(fake)

    assert result == EntryRemainderCancelConfirmation(
        "instance-1", "cycle-1", "entry_remainder_cancelled", "0.004"
    )
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "POST"
    assert (
        sent.url.raw_path
        == b"/v1/strategy-instances/instance-1/trade-cycles/cycle-1/entry-remainder/cancel"
    )
    assert sent.headers["content-type"] == "application/json"
    assert json.loads(sent.content) == {}


@pytest.mark.parametrize("executed_quantity", ["0.010", None])
def test_cancel_entry_remainder_accepts_already_terminal_with_or_without_quantity(
    executed_quantity: object,
) -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            remainder_body(
                status="entry_order_already_terminal", executed_quantity=executed_quantity
            ),
        )
    )

    result = cancel_entry_remainder(fake)

    assert result.status == "entry_order_already_terminal"
    assert result.executed_quantity == executed_quantity


@pytest.mark.parametrize(
    "body",
    [
        remainder_body(trade_cycle_id="cycle-2"),
        remainder_body(status="trade_cycle_closed"),
        remainder_body(executed_quantity="0"),
        remainder_body(executed_quantity=0.004),
        {**remainder_body(), "extra": 1},
        {k: v for k, v in remainder_body().items() if k != "executed_quantity"},
    ],
)
def test_cancel_entry_remainder_rejects_any_other_success_body(body: object) -> None:
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(PositionManagementExecutionProtocolError):
        cancel_entry_remainder(fake)


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (422, "entry_not_filled"),
        (422, "unknown_trade_cycle_binding"),
        (400, "malformed_json"),
        (415, "unsupported_media_type"),
    ],
)
def test_cancel_entry_remainder_documented_rejections_are_public_errors(
    status_code: int, code: str
) -> None:
    fake = FakeAbi(
        lambda _: json_response(status_code, {"error": {"code": code, "message": "rejected"}})
    )

    with pytest.raises(PositionManagementExecutionPublicError) as raised:
        cancel_entry_remainder(fake)

    assert raised.value.code == code


def test_cancel_entry_remainder_internal_error_is_unavailable() -> None:
    fake = FakeAbi(
        lambda _: json_response(500, {"error": {"code": "internal_error", "message": "x"}})
    )

    with pytest.raises(PositionManagementExecutionUnavailable):
        cancel_entry_remainder(fake)


def test_cancel_entry_remainder_undocumented_code_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: json_response(422, {"error": {"code": "position_not_open", "message": "x"}})
    )

    with pytest.raises(PositionManagementExecutionProtocolError):
        cancel_entry_remainder(fake)


def test_cancel_entry_remainder_timeout_and_network_failure_are_typed_and_not_retried() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    slow = FakeAbi(timeout)
    with pytest.raises(PositionManagementExecutionTimeout):
        cancel_entry_remainder(slow)
    assert len(slow.requests) == 1

    down = FakeAbi(network_failure)
    with pytest.raises(PositionManagementExecutionNetworkFailure):
        cancel_entry_remainder(down)
    assert len(down.requests) == 1
