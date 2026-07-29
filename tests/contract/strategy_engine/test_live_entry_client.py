import json
from collections.abc import Callable

import httpx
import pytest

from strategy_runtime.infrastructure.strategy_engine.http_projection_client import (
    HttpxStrategyEngineLiveEntryAdapter,
)
from strategy_runtime.runtime.engine.errors import (
    StrategyEngineMarketStreamNotFound,
    StrategyEngineProjectionNetworkFailure,
    StrategyEngineProjectionProtocolError,
    StrategyEngineProjectionPublicError,
    StrategyEngineProjectionTimeout,
    StrategyEngineProjectionUnavailable,
)
from strategy_runtime.runtime.engine.live_entry import LiveEntryProjectionRequest
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.routing.errors import (
    StrategyEngineProjectionUnavailable as RoutedStrategyEngineProjectionUnavailable,
)

ResponseFactory = Callable[[httpx.Request], httpx.Response]


class FakeEngine:
    def __init__(self, response_factory: ResponseFactory) -> None:
        self.requests: list[httpx.Request] = []
        self._response_factory = response_factory
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response_factory(request)


def test_request_shape_is_closed_and_preserves_raw_spec_and_decimals() -> None:
    request = make_request(
        raw_spec={"nested": {"weights": [1, "2", None]}, "z": True},
        target_bar_open_time_ms=1720000000000,
    )
    fake = FakeEngine(lambda _: json_response(200, {"desired_entry": None}))

    result = project(fake, request)

    assert result.desired_entry is None
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "POST"
    assert sent.url.path == "/v1/strategy-evaluations/live-entry"
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["accept"] == "application/json"
    body = json.loads(sent.content)
    assert body == {
        "strategy_id": "ema_pullback",
        "raw_spec": {"nested": {"weights": [1, "2", None]}, "z": True},
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "target_bar_open_time_ms": 1720000000000,
    }
    assert isinstance(body["target_bar_open_time_ms"], int)
    assert body["target_bar_open_time_ms"] is not True
    assert "strategy_instance_id" not in body
    assert "trade_cycle_id" not in body
    assert "instance_id" not in body
    assert "executed_entry_price" not in body


def test_decodes_present_desired_entry_with_domain_normalization() -> None:
    request = make_request()
    fake = FakeEngine(lambda _: json_response(200, {"desired_entry": desired_entry_body()}))

    result = project(fake, request)

    assert result.desired_entry == DesiredEntry(
        side="long",
        source_plan_bar_open_time_ms=1785000000000,
        planned_entry_price="-123",
        initial_stop_price="999",
        initial_take_price="1",
        locked_exit_profile="default",
    )


def test_decodes_absent_desired_entry_as_none() -> None:
    fake = FakeEngine(lambda _: json_response(200, {"desired_entry": None}))

    result = project(fake, make_request())

    assert result.desired_entry is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"extra": True}),
        lambda body: body["desired_entry"].pop("side"),
        lambda body: body["desired_entry"].update({"extra": True}),
        lambda body: body["desired_entry"].update({"side": "north"}),
        lambda body: body["desired_entry"].update({"source_plan_bar_open_time_ms": True}),
        lambda body: body["desired_entry"].update({"source_plan_bar_open_time_ms": 1.5}),
        lambda body: body["desired_entry"].update({"planned_entry_price": -123}),
        lambda body: body["desired_entry"].update({"initial_take_price": "0"}),
        lambda body: body["desired_entry"].update({"initial_take_price": None}),
    ],
)
def test_malformed_success_body_fails_closed(mutate: Callable[[dict[str, object]], object]) -> None:
    body: dict[str, object] = {"desired_entry": desired_entry_body()}
    mutate(body)
    fake = FakeEngine(lambda _: json_response(200, body))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_undocumented_2xx_does_not_acknowledge_success() -> None:
    fake = FakeEngine(lambda _: json_response(201, {"desired_entry": None}))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())


def test_market_stream_not_found_is_distinguished() -> None:
    fake = FakeEngine(
        lambda _: json_response(
            404,
            error_envelope("market_stream_not_found", "no stream", {}, "req-1"),
        )
    )

    with pytest.raises(StrategyEngineMarketStreamNotFound) as raised:
        project(fake, make_request())

    error = raised.value
    assert isinstance(error, StrategyEngineProjectionPublicError)
    assert isinstance(error, StrategyEngineProjectionUnavailable)
    assert isinstance(error, RoutedStrategyEngineProjectionUnavailable)
    assert error.status_code == 404
    assert error.code == "market_stream_not_found"
    assert error.message == "no stream"
    assert error.details == {}
    assert error.request_id == "req-1"


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (409, "unsupported_capability"),
        (422, "invalid_request"),
        (500, "internal_error"),
        (501, "unsupported_capability"),
        (502, "upstream_contract_error"),
        (503, "market_data_unavailable"),
        (404, "unknown_resource"),
    ],
)
def test_documented_public_errors_preserve_fields(status_code: int, code: str) -> None:
    fake = FakeEngine(
        lambda _: json_response(
            status_code,
            error_envelope(code, "business rejection", {"field": "ticker"}, "req-2"),
        )
    )

    with pytest.raises(StrategyEngineProjectionPublicError) as raised:
        project(fake, make_request())

    assert not isinstance(raised.value, StrategyEngineMarketStreamNotFound)
    error = raised.value
    assert error.status_code == status_code
    assert error.code == code
    assert error.message == "business rejection"
    assert error.details == {"field": "ticker"}
    assert error.request_id == "req-2"
    assert isinstance(error, StrategyEngineProjectionUnavailable)


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (404, []),
        (404, {"error": "market_stream_not_found", "message": "m", "details": {}}),
        (
            404,
            {
                "error": "market_stream_not_found",
                "message": "m",
                "details": {},
                "request_id": "r",
                "extra": True,
            },
        ),
        (422, {"error": "", "message": "m", "details": {}, "request_id": "r"}),
        (422, {"error": "invalid_request", "message": "", "details": {}, "request_id": "r"}),
        (422, {"error": "invalid_request", "message": "m", "details": [], "request_id": "r"}),
        (422, {"error": "invalid_request", "message": "m", "details": {}, "request_id": ""}),
        (422, {"error": 1, "message": "m", "details": {}, "request_id": "r"}),
    ],
)
def test_invalid_public_error_envelope_fails_closed(status_code: int, body: object) -> None:
    fake = FakeEngine(lambda _: json_response(status_code, body))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_undocumented_status_fails_closed() -> None:
    fake = FakeEngine(lambda _: json_response(418, {"anything": True}))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())


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
            content=b'{"desired_entry":null,"desired_entry":null}',
            headers={"content-type": "application/json"},
        ),
    ],
)
def test_invalid_content_type_utf8_or_json_fails_closed(response: httpx.Response) -> None:
    fake = FakeEngine(lambda _: response)

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_timeout_is_typed_and_not_retried() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fake = FakeEngine(timeout)

    with pytest.raises(StrategyEngineProjectionTimeout):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_network_failure_is_typed_and_not_retried() -> None:
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    fake = FakeEngine(network_failure)

    with pytest.raises(StrategyEngineProjectionNetworkFailure):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_programming_failure_is_not_relabelled() -> None:
    def programming_failure(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug")

    fake = FakeEngine(programming_failure)

    with pytest.raises(RuntimeError, match="bug"):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_redirect_is_not_followed_and_fails_closed() -> None:
    fake = FakeEngine(
        lambda _: httpx.Response(
            307,
            headers={
                "location": "http://other.test/target",
                "content-type": "application/json",
            },
            json={"desired_entry": None},
        )
    )

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())

    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "error_cls",
    [
        StrategyEngineProjectionPublicError,
        StrategyEngineMarketStreamNotFound,
        StrategyEngineProjectionTimeout,
        StrategyEngineProjectionNetworkFailure,
        StrategyEngineProjectionProtocolError,
    ],
)
def test_every_failure_branch_is_unavailable_subtype(
    error_cls: type[BaseException],
) -> None:
    assert issubclass(error_cls, StrategyEngineProjectionUnavailable)
    assert issubclass(error_cls, RoutedStrategyEngineProjectionUnavailable)


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        HttpxStrategyEngineLiveEntryAdapter(
            base_url="http://engine.test",
            timeout_seconds=timeout_seconds,
            transport=httpx.MockTransport(lambda _: json_response(500, {})),
        )


def project(fake: FakeEngine, request: LiveEntryProjectionRequest) -> object:
    with HttpxStrategyEngineLiveEntryAdapter(
        base_url="http://engine.test",
        timeout_seconds=0.25,
        transport=fake.transport,
    ) as adapter:
        return adapter.project_live_entry(request)


def make_request(
    *,
    strategy_id: str = "ema_pullback",
    raw_spec: dict[str, object] | None = None,
    ticker: str = "BTCUSDT.P",
    base_timeframe: str = "5m",
    target_bar_open_time_ms: int = 1720000000000,
) -> LiveEntryProjectionRequest:
    return LiveEntryProjectionRequest(
        strategy_id=strategy_id,
        raw_spec=raw_spec if raw_spec is not None else {"kind": "ema_pullback"},
        ticker=ticker,
        base_timeframe=base_timeframe,
        target_bar_open_time_ms=target_bar_open_time_ms,
    )


def desired_entry_body() -> dict[str, object]:
    return {
        "side": "long",
        "source_plan_bar_open_time_ms": 1785000000000,
        "planned_entry_price": "-123",
        "initial_stop_price": "999",
        "initial_take_price": "1",
        "locked_exit_profile": "default",
    }


def error_envelope(
    code: str, message: str, details: dict[str, object], request_id: str
) -> dict[str, object]:
    return {"error": code, "message": message, "details": details, "request_id": request_id}


def json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"content-type": "application/json; charset=utf-8"},
    )
