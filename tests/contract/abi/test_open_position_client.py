from collections.abc import Callable

import httpx
import pytest

from strategy_runtime.infrastructure.abi.http_open_position import (
    HttpxAbiOpenPositionLookupAdapter,
)
from strategy_runtime.runtime.open_position.errors import (
    OpenPositionLookupNetworkFailure,
    OpenPositionLookupProtocolError,
    OpenPositionLookupPublicError,
    OpenPositionLookupTimeout,
    OpenPositionLookupUnavailable,
)
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupRequest,
    OpenPositionLookupResponse,
)

ResponseFactory = Callable[[httpx.Request], httpx.Response]


class FakeAbi:
    def __init__(self, response_factory: ResponseFactory) -> None:
        self.requests: list[httpx.Request] = []
        self._response_factory = response_factory
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response_factory(request)


def test_closed_position_request_is_a_bodyless_get() -> None:
    fake = FakeAbi(lambda _: json_response(200, closed_body()))

    result = lookup(fake, make_request(strategy_instance_id="instance-1", trade_cycle_id="cycle-1"))

    assert result == OpenPositionLookupResponse(position_open=False)
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "GET"
    assert (
        sent.url.raw_path == b"/v1/strategy-instances/instance-1/trade-cycles/cycle-1/open-position"
    )
    assert sent.content == b""
    assert "content-type" not in sent.headers
    assert sent.headers["accept"] == "application/json"


@pytest.mark.parametrize(
    ("strategy_instance_id", "expected_path"),
    [
        (
            "instance/future %",
            b"/v1/strategy-instances/instance%2Ffuture%20%25/trade-cycles/cycle/open-position",
        ),
        (
            "цикл id",
            b"/v1/strategy-instances/%D1%86%D0%B8%D0%BA%D0%BB%20id/trade-cycles/cycle/open-position",
        ),
        (".", b"/v1/strategy-instances/%2E/trade-cycles/cycle/open-position"),
        ("..", b"/v1/strategy-instances/%2E%2E/trade-cycles/cycle/open-position"),
        ("%", b"/v1/strategy-instances/%25/trade-cycles/cycle/open-position"),
        ("/", b"/v1/strategy-instances/%2F/trade-cycles/cycle/open-position"),
    ],
)
def test_strategy_instance_segment_is_encoded_as_one_opaque_utf8_segment(
    strategy_instance_id: str, expected_path: bytes
) -> None:
    fake = FakeAbi(lambda _: json_response(200, closed_body()))

    lookup(fake, make_request(strategy_instance_id=strategy_instance_id, trade_cycle_id="cycle"))

    assert fake.requests[0].url.raw_path == expected_path


@pytest.mark.parametrize(
    ("trade_cycle_id", "expected_path"),
    [
        (
            "cycle/future %",
            b"/v1/strategy-instances/instance/trade-cycles/cycle%2Ffuture%20%25/open-position",
        ),
        (
            "цикл id",
            b"/v1/strategy-instances/instance/trade-cycles/%D1%86%D0%B8%D0%BA%D0%BB%20id/open-position",
        ),
        (".", b"/v1/strategy-instances/instance/trade-cycles/%2E/open-position"),
        ("..", b"/v1/strategy-instances/instance/trade-cycles/%2E%2E/open-position"),
        ("%", b"/v1/strategy-instances/instance/trade-cycles/%25/open-position"),
        ("/", b"/v1/strategy-instances/instance/trade-cycles/%2F/open-position"),
    ],
)
def test_trade_cycle_segment_is_encoded_as_one_opaque_utf8_segment(
    trade_cycle_id: str, expected_path: bytes
) -> None:
    fake = FakeAbi(lambda _: json_response(200, closed_body()))

    lookup(fake, make_request(strategy_instance_id="instance", trade_cycle_id=trade_cycle_id))

    assert fake.requests[0].url.raw_path == expected_path


def test_decodes_open_position_with_domain_normalized_decimal() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "position_open": True,
                "first_fill_at_ms": 1720000000000,
                "average_entry_price": "+061234.500e0",
            },
        )
    )

    result = lookup(fake, make_request())

    assert result == OpenPositionLookupResponse(
        position_open=True,
        first_fill_at_ms=1720000000000,
        average_entry_price="61234.5",
    )


@pytest.mark.parametrize("first_fill_at_ms", [0, -1])
def test_non_positive_first_fill_at_ms_is_rejected(first_fill_at_ms: int) -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "position_open": True,
                "first_fill_at_ms": first_fill_at_ms,
                "average_entry_price": "61234.5",
            },
        )
    )

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


def test_unexpected_404_never_becomes_closed_position() -> None:
    fake = FakeAbi(lambda _: json_response(404, {"anything": True}))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"extra": True}),
        lambda body: body.pop("average_entry_price"),
        lambda body: body.update({"position_open": "true"}),
        lambda body: body.update({"first_fill_at_ms": True}),
        lambda body: body.update({"first_fill_at_ms": 1.5}),
        lambda body: body.update({"average_entry_price": 61234.5}),
    ],
)
def test_malformed_open_success_body_fails_closed(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    body: dict[str, object] = {
        "position_open": True,
        "first_fill_at_ms": 1720000000000,
        "average_entry_price": "61234.5",
    }
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_legacy_pre_alignment_success_shape_is_rejected() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "position_open": False,
                "entry_bar_open_time_ms": None,
                "executed_entry_price": None,
            },
        )
    )

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


@pytest.mark.parametrize(
    "body",
    [
        {
            "position_open": False,
            "first_fill_at_ms": 1720000000000,
            "average_entry_price": None,
        },
        {
            "position_open": False,
            "first_fill_at_ms": None,
            "average_entry_price": "61234.5",
        },
        {
            "position_open": True,
            "first_fill_at_ms": None,
            "average_entry_price": "61234.5",
        },
        {
            "position_open": True,
            "first_fill_at_ms": 1720000000000,
            "average_entry_price": None,
        },
    ],
)
def test_contradictory_facts_fail_closed(body: dict[str, object]) -> None:
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


def test_validation_failed_requires_and_preserves_details_array() -> None:
    body = {
        "error": {
            "code": "validation_failed",
            "message": "request validation failed",
            "details": [{"path": "/path/trade_cycle_id", "message": "must be non-empty"}],
        }
    }
    fake = FakeAbi(lambda _: json_response(422, body))

    with pytest.raises(OpenPositionLookupPublicError) as raised:
        lookup(fake, make_request())

    error = raised.value
    assert error.status_code == 422
    assert error.code == "validation_failed"
    assert error.message == "request validation failed"
    details = error.details
    assert isinstance(details, tuple)
    assert list(details) == [{"path": "/path/trade_cycle_id", "message": "must be non-empty"}]


@pytest.mark.parametrize(
    "details",
    [
        None,
        [],
        [{"path": "/x"}],
        [{"message": "x"}],
        [{"path": "/x", "message": "x", "extra": True}],
        "not-an-array",
    ],
)
def test_validation_failed_with_invalid_details_fails_closed(details: object) -> None:
    body: dict[str, object] = {
        "error": {"code": "validation_failed", "message": "bad"},
    }
    if details is not None:
        body["error"]["details"] = details  # type: ignore[index]
    fake = FakeAbi(lambda _: json_response(422, body))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


@pytest.mark.parametrize("code", ["unknown_trade_cycle_binding", "unsupported_exchange_scope"])
def test_no_details_error_codes_preserve_fields_without_details(code: str) -> None:
    fake = FakeAbi(lambda _: json_response(422, {"error": {"code": code, "message": "rejected"}}))

    with pytest.raises(OpenPositionLookupPublicError) as raised:
        lookup(fake, make_request())

    error = raised.value
    assert error.status_code == 422
    assert error.code == code
    assert error.message == "rejected"
    assert error.details is None


@pytest.mark.parametrize("code", ["unknown_trade_cycle_binding", "unsupported_exchange_scope"])
def test_no_details_error_codes_reject_a_details_field(code: str) -> None:
    body = {"error": {"code": code, "message": "rejected", "details": {"x": 1}}}
    fake = FakeAbi(lambda _: json_response(422, body))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


def test_undocumented_422_error_code_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: json_response(422, {"error": {"code": "made_up_code", "message": "bad"}})
    )

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"error": {"code": "validation_failed", "message": "bad", "extra": True}},
        {"error": {"code": "validation_failed", "message": "bad"}, "extra": True},
        {"error": {"code": "", "message": "bad"}},
        {"error": {"code": "unknown_trade_cycle_binding", "message": ""}},
        {"error": {"code": 1, "message": "bad"}},
        {"error": {"message": "missing code"}},
        {"error": "not an object"},
    ],
)
def test_invalid_public_error_envelope_fails_closed(body: object) -> None:
    fake = FakeAbi(lambda _: json_response(422, body))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_400_is_not_a_documented_status_and_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: json_response(400, {"error": {"code": "validation_failed", "message": "bad"}})
    )

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


def test_documented_500_internal_error_is_unavailable_not_public_error() -> None:
    fake = FakeAbi(
        lambda _: json_response(500, {"error": {"code": "internal_error", "message": "boom"}})
    )

    with pytest.raises(OpenPositionLookupUnavailable) as raised:
        lookup(fake, make_request())

    assert not isinstance(raised.value, OpenPositionLookupPublicError)


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "not_internal_error", "message": "boom"}},
        {"error": {"code": "internal_error", "message": "boom", "details": {}}},
        {"error": {"message": "missing code"}},
        {"error": "not an object"},
        [],
    ],
)
def test_500_outside_documented_internal_error_shape_fails_closed(body: object) -> None:
    fake = FakeAbi(lambda _: json_response(500, body))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


@pytest.mark.parametrize("status_code", [501, 502, 503])
def test_undocumented_5xx_status_fails_closed_not_unavailable(status_code: int) -> None:
    fake = FakeAbi(
        lambda _: json_response(
            status_code, {"error": {"code": "internal_error", "message": "boom"}}
        )
    )

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


def test_undocumented_status_fails_closed() -> None:
    fake = FakeAbi(lambda _: json_response(403, {"anything": True}))

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"{}", headers={"content-type": "text/plain"}),
        httpx.Response(200, content=b"{}", headers={}),
        httpx.Response(
            200,
            content=b"{}",
            headers={"content-type": "application/json; charset=utf-16"},
        ),
        httpx.Response(
            200,
            content=b"{",
            headers={"content-type": "application/json; charset=utf-8"},
        ),
        httpx.Response(
            200,
            content=b"\xff",
            headers={"content-type": "application/json; charset=utf-8"},
        ),
        httpx.Response(
            200,
            content=b'{"position_open":false,"position_open":false,'
            b'"first_fill_at_ms":null,"average_entry_price":null}',
            headers={"content-type": "application/json"},
        ),
    ],
)
def test_invalid_content_type_utf8_or_json_fails_closed(response: httpx.Response) -> None:
    fake = FakeAbi(lambda _: response)

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_timeout_is_typed_and_not_retried() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fake = FakeAbi(timeout)

    with pytest.raises(OpenPositionLookupTimeout):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_network_failure_is_typed_and_not_retried() -> None:
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    fake = FakeAbi(network_failure)

    with pytest.raises(OpenPositionLookupNetworkFailure):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_programming_failure_is_not_relabelled() -> None:
    def programming_failure(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug")

    fake = FakeAbi(programming_failure)

    with pytest.raises(RuntimeError, match="bug"):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_redirect_is_not_followed_and_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: httpx.Response(
            307,
            headers={
                "location": "http://other.test/target",
                "content-type": "application/json",
            },
            json=closed_body(),
        )
    )

    with pytest.raises(OpenPositionLookupProtocolError):
        lookup(fake, make_request())

    assert len(fake.requests) == 1


def test_every_transport_failure_is_an_unavailable_subtype() -> None:
    assert issubclass(OpenPositionLookupTimeout, OpenPositionLookupUnavailable)
    assert issubclass(OpenPositionLookupNetworkFailure, OpenPositionLookupUnavailable)


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        HttpxAbiOpenPositionLookupAdapter(
            base_url="http://abi.test",
            timeout_seconds=timeout_seconds,
            transport=httpx.MockTransport(lambda _: json_response(500, {})),
        )


def lookup(fake: FakeAbi, request: OpenPositionLookupRequest) -> OpenPositionLookupResponse:
    with HttpxAbiOpenPositionLookupAdapter(
        base_url="http://abi.test",
        timeout_seconds=0.25,
        transport=fake.transport,
    ) as adapter:
        return adapter.lookup(request)


def make_request(
    *, strategy_instance_id: str = "instance", trade_cycle_id: str = "cycle"
) -> OpenPositionLookupRequest:
    return OpenPositionLookupRequest(
        strategy_instance_id=strategy_instance_id, trade_cycle_id=trade_cycle_id
    )


def closed_body() -> dict[str, object]:
    return {
        "position_open": False,
        "first_fill_at_ms": None,
        "average_entry_price": None,
    }


def json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"content-type": "application/json; charset=utf-8"},
    )
