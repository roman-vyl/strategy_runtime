import json
from collections.abc import Callable

import httpx
import pytest

from strategy_runtime.infrastructure.strategy_engine.http_projection_client import (
    HttpxStrategyEngineFeaturePlanAdapter,
)
from strategy_runtime.runtime.engine.errors import (
    StrategyEngineProjectionNetworkFailure,
    StrategyEngineProjectionProtocolError,
    StrategyEngineProjectionPublicError,
    StrategyEngineProjectionTimeout,
)
from strategy_runtime.utility.deployment_catalog.models import freeze_json

ResponseFactory = Callable[[httpx.Request], httpx.Response]
RAW_SPEC = freeze_json({"anchor_stack": {"fast": {"period": 200}}, "components": {}})


class FakeEngine:
    def __init__(self, response_factory: ResponseFactory) -> None:
        self.requests: list[httpx.Request] = []
        self._response_factory = response_factory
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response_factory(request)


def json_response(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body)


def build(fake: FakeEngine, strategy_id: str = "ema_pullback") -> object:
    adapter = HttpxStrategyEngineFeaturePlanAdapter(
        base_url="http://engine.test", timeout_seconds=1.0, transport=fake.transport
    )
    with adapter:
        return adapter.build_feature_plan(strategy_id, RAW_SPEC)  # type: ignore[arg-type]


def test_posts_the_strategy_and_returns_the_plan_object() -> None:
    plan = {"plan_version": "bbb_v1", "anchor_columns": {"fast": "a"}, "features": []}
    fake = FakeEngine(lambda _: json_response(200, plan))

    assert build(fake) == plan

    (request,) = fake.requests
    assert request.method == "POST"
    assert request.url.path == "/v1/strategies/ema_pullback/feature-plan"
    assert json.loads(request.content) == {
        "strategy_id": "ema_pullback",
        "raw_spec": {"anchor_stack": {"fast": {"period": 200}}, "components": {}},
    }


def test_strategy_id_is_quoted_in_the_path() -> None:
    fake = FakeEngine(lambda _: json_response(200, {}))

    build(fake, "a/b c")

    assert fake.requests[0].url.raw_path == b"/v1/strategies/a%2Fb%20c/feature-plan"


def test_engine_rejection_keeps_status_code_and_message() -> None:
    envelope = {"error": "invalid_request", "message": "bad", "details": {}, "request_id": "r1"}
    fake = FakeEngine(lambda _: json_response(422, envelope))

    with pytest.raises(StrategyEngineProjectionPublicError) as raised:
        build(fake)

    assert (raised.value.status_code, raised.value.code, raised.value.message) == (
        422,
        "invalid_request",
        "bad",
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=[1]),
        httpx.Response(200, content=b"nope", headers={"content-type": "application/json"}),
        httpx.Response(200, content=b"{}", headers={"content-type": "text/plain"}),
        httpx.Response(418, json={}),
        httpx.Response(422, json={"unexpected": True}),
    ],
)
def test_anything_outside_the_contract_is_a_protocol_error(response: httpx.Response) -> None:
    fake = FakeEngine(lambda _: response)

    with pytest.raises(StrategyEngineProjectionProtocolError):
        build(fake)


def test_timeout_and_network_failure_are_typed() -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("t")

    def network(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("n")

    with pytest.raises(StrategyEngineProjectionTimeout):
        build(FakeEngine(timeout))
    with pytest.raises(StrategyEngineProjectionNetworkFailure):
        build(FakeEngine(network))
