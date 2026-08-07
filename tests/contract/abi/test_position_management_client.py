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
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
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
            },
        )
    )

    result = apply_protection(
        fake,
        make_protection_command(desired_protection=DesiredProtection("99000", None)),
    )

    assert result.confirmed_protection == DesiredProtection("99000", None)
    assert json.loads(fake.requests[0].content) == {"stop_price": "99000", "take_price": None}


# -- close_position: request shape -------------------------------------------


def test_close_position_sends_a_bodyless_delete() -> None:
    fake = FakeAbi(lambda _: json_response(200, closed_body()))

    result = close_position(fake, make_close_command())

    assert result == PositionClosedConfirmation(
        strategy_instance_id="instance-1", trade_cycle_id="cycle-1"
    )
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "DELETE"
    assert (
        sent.url.raw_path == b"/v1/strategy-instances/instance-1/trade-cycles/cycle-1/open-position"
    )
    assert sent.content == b""
    assert "content-type" not in sent.headers


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
            b"/v1/strategy-instances/instance/trade-cycles/cycle%2Ffuture%20%25/open-position",
        ),
        (".", b"/v1/strategy-instances/instance/trade-cycles/%2E/open-position"),
        ("..", b"/v1/strategy-instances/instance/trade-cycles/%2E%2E/open-position"),
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
