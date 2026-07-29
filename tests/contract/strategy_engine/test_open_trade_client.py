import json
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from strategy_runtime.infrastructure.strategy_engine.http_projection_client import (
    HttpxStrategyEngineOpenTradeAdapter,
)
from strategy_runtime.runtime.engine.errors import (
    StrategyEngineMarketStreamNotFound,
    StrategyEngineProjectionNetworkFailure,
    StrategyEngineProjectionProtocolError,
    StrategyEngineProjectionPublicError,
    StrategyEngineProjectionTimeout,
    StrategyEngineProjectionUnavailable,
)
from strategy_runtime.runtime.engine.open_trade import OpenTradeProjectionRequest
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection
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


def test_request_regroups_into_executed_trade_receipt_without_new_facts() -> None:
    request = make_request()
    fake = FakeEngine(lambda _: json_response(200, success_body()))

    project(fake, request)

    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "POST"
    assert sent.url.path == "/v1/strategy-evaluations/open-trade"
    assert sent.headers["content-type"] == "application/json"
    body = json.loads(sent.content)
    assert body == {
        "strategy_id": "ema_pullback",
        "raw_spec": {"kind": "ema_pullback"},
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "target_bar_open_time_ms": 1720000000000,
        "executed_trade_receipt": {
            "side": "long",
            "source_plan_bar_open_time_ms": 1785000000000,
            "entry_bar_open_time_ms": 1785300000000,
            "planned_entry_price": "-123",
            "initial_stop_price": "999",
            "initial_take_price": "1",
            "locked_exit_profile": "default",
        },
    }
    assert isinstance(body["executed_trade_receipt"]["entry_bar_open_time_ms"], int)
    assert "strategy_instance_id" not in body
    assert "trade_cycle_id" not in body
    assert "instance_id" not in body
    assert "executed_entry_price" not in body
    receipt = body["executed_trade_receipt"]
    assert "executed_entry_price" not in receipt
    assert "strategy_instance_id" not in receipt
    assert "trade_cycle_id" not in receipt


def test_boolean_target_bar_open_time_ms_is_rejected_before_http_call() -> None:
    request = replace(make_request(), target_bar_open_time_ms=True)
    fake = FakeEngine(lambda _: json_response(200, success_body()))

    with pytest.raises(TypeError):
        project(fake, request)

    assert fake.requests == []


def test_boolean_entry_bar_open_time_ms_is_rejected_before_http_call() -> None:
    request = replace(make_request(), entry_bar_open_time_ms=True)
    fake = FakeEngine(lambda _: json_response(200, success_body()))

    with pytest.raises(TypeError):
        project(fake, request)

    assert fake.requests == []


def test_non_object_raw_spec_is_rejected_before_http_call() -> None:
    request = replace(make_request(), raw_spec="not-an-object")
    fake = FakeEngine(lambda _: json_response(200, success_body()))

    with pytest.raises(TypeError):
        project(fake, request)

    assert fake.requests == []


def test_wrong_type_desired_entry_is_rejected_before_http_call() -> None:
    request = replace(make_request(), desired_entry="not-a-desired-entry")
    fake = FakeEngine(lambda _: json_response(200, success_body()))

    with pytest.raises(TypeError):
        project(fake, request)

    assert fake.requests == []


def test_decodes_complete_projection_response() -> None:
    fake = FakeEngine(lambda _: json_response(200, success_body()))

    result = project(fake, make_request())

    assert result.desired_protection == DesiredProtection(stop_price="100", take_price="200")
    assert result.close_signal == CloseSignal(
        active=False, reason=None, component_id=None, layer=None
    )
    assert dict(result.diagnostics) == {"nested": {"x": 1}, "list": (1, 2, 3)}


def test_decodes_null_take_price_and_active_close_signal() -> None:
    body = success_body()
    body["desired_protection"]["take_price"] = None
    body["close_signal"] = {
        "active": True,
        "reason": "stop_hit",
        "component_id": "trailing",
        "layer": "protective",
    }
    fake = FakeEngine(lambda _: json_response(200, body))

    result = project(fake, make_request())

    assert result.desired_protection.take_price is None
    assert result.close_signal == CloseSignal(
        active=True, reason="stop_hit", component_id="trailing", layer="protective"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"extra": True}),
        lambda body: body.pop("close_signal"),
        lambda body: body["desired_protection"].update({"extra": True}),
        lambda body: body["desired_protection"].update({"stop_price": 100}),
        lambda body: body["close_signal"].update({"active": "yes"}),
        lambda body: body["close_signal"].update({"extra": True}),
        lambda body: body.update({"diagnostics": []}),
        lambda body: body.update({"diagnostics": "opaque"}),
        lambda body: body.update({"diagnostics": None}),
    ],
)
def test_malformed_success_body_fails_closed(mutate: Callable[[dict[str, object]], object]) -> None:
    body = success_body()
    mutate(body)
    fake = FakeEngine(lambda _: json_response(200, body))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())

    assert len(fake.requests) == 1


def test_undocumented_2xx_does_not_acknowledge_success() -> None:
    fake = FakeEngine(lambda _: json_response(201, success_body()))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())


def test_market_stream_not_found_is_distinguished() -> None:
    fake = FakeEngine(
        lambda _: json_response(
            404,
            {
                "error": "market_stream_not_found",
                "message": "no stream",
                "details": {},
                "request_id": "req-1",
            },
        )
    )

    with pytest.raises(StrategyEngineMarketStreamNotFound) as raised:
        project(fake, make_request())

    assert raised.value.status_code == 404
    assert raised.value.code == "market_stream_not_found"


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (409, "target_bar_not_committed"),
        (422, "evaluation_invariant_broken"),
        (500, "internal_error"),
        (502, "upstream_contract_error"),
        (503, "trade_history_unavailable"),
    ],
)
def test_documented_public_errors_preserve_fields(status_code: int, code: str) -> None:
    fake = FakeEngine(
        lambda _: json_response(
            status_code,
            {
                "error": code,
                "message": "business rejection",
                "details": {"field": "ticker"},
                "request_id": "req-2",
            },
        )
    )

    with pytest.raises(StrategyEngineProjectionPublicError) as raised:
        project(fake, make_request())

    error = raised.value
    assert not isinstance(error, StrategyEngineMarketStreamNotFound)
    assert error.status_code == status_code
    assert error.code == code
    assert error.message == "business rejection"
    assert error.details == {"field": "ticker"}
    assert error.request_id == "req-2"


def test_undocumented_status_fails_closed() -> None:
    fake = FakeEngine(lambda _: json_response(418, {"anything": True}))

    with pytest.raises(StrategyEngineProjectionProtocolError):
        project(fake, make_request())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"{}", headers={"content-type": "text/plain"}),
        httpx.Response(200, content=b"{", headers={"content-type": "application/json"}),
        httpx.Response(
            200, content=b"\xff", headers={"content-type": "application/json; charset=utf-8"}
        ),
    ],
)
def test_invalid_content_type_or_json_fails_closed(response: httpx.Response) -> None:
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
            json=success_body(),
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
def test_every_failure_branch_is_unavailable_subtype(error_cls: type[BaseException]) -> None:
    assert issubclass(error_cls, StrategyEngineProjectionUnavailable)
    assert issubclass(error_cls, RoutedStrategyEngineProjectionUnavailable)


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        HttpxStrategyEngineOpenTradeAdapter(
            base_url="http://engine.test",
            timeout_seconds=timeout_seconds,
            transport=httpx.MockTransport(lambda _: json_response(500, {})),
        )


def project(fake: FakeEngine, request: OpenTradeProjectionRequest) -> object:
    with HttpxStrategyEngineOpenTradeAdapter(
        base_url="http://engine.test",
        timeout_seconds=0.25,
        transport=fake.transport,
    ) as adapter:
        return adapter.project_open_trade(request)


def make_request(
    *,
    strategy_id: str = "ema_pullback",
    ticker: str = "BTCUSDT.P",
    base_timeframe: str = "5m",
    target_bar_open_time_ms: int = 1720000000000,
    entry_bar_open_time_ms: int = 1785300000000,
) -> OpenTradeProjectionRequest:
    return OpenTradeProjectionRequest(
        strategy_id=strategy_id,
        raw_spec={"kind": "ema_pullback"},
        ticker=ticker,
        base_timeframe=base_timeframe,
        target_bar_open_time_ms=target_bar_open_time_ms,
        desired_entry=DesiredEntry(
            side="long",
            source_plan_bar_open_time_ms=1785000000000,
            planned_entry_price="-123",
            initial_stop_price="999",
            initial_take_price="1",
            locked_exit_profile="default",
        ),
        entry_bar_open_time_ms=entry_bar_open_time_ms,
    )


def success_body() -> dict[str, object]:
    return {
        "desired_protection": {"stop_price": "100", "take_price": "200"},
        "close_signal": {
            "active": False,
            "reason": None,
            "component_id": None,
            "layer": None,
        },
        "diagnostics": {"nested": {"x": 1}, "list": [1, 2, 3]},
    }


def json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"content-type": "application/json; charset=utf-8"},
    )
