"""One-shot HTTP adapters for the Strategy Engine live-entry/open-trade endpoints."""

import math
from types import TracebackType

import httpx

from strategy_runtime.infrastructure.strategy_engine.wire_codec import (
    decode_live_entry_response,
    decode_open_trade_response,
    encode_live_entry_request,
    encode_open_trade_request,
)
from strategy_runtime.runtime.engine.errors import (
    StrategyEngineProjectionNetworkFailure,
    StrategyEngineProjectionTimeout,
)
from strategy_runtime.runtime.engine.live_entry import (
    LiveEntryProjectionRequest,
    LiveEntryProjectionResponse,
)
from strategy_runtime.runtime.engine.open_trade import (
    OpenTradeProjectionRequest,
    OpenTradeProjectionResponse,
)

_LIVE_ENTRY_PATH = "/v1/strategy-evaluations/live-entry"
_OPEN_TRADE_PATH = "/v1/strategy-evaluations/open-trade"


class HttpxStrategyEngineLiveEntryAdapter:
    """Synchronous scalar adapter with one bounded, non-retried HTTP attempt."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = _build_client(base_url, timeout_seconds, transport)

    def project_live_entry(
        self, request: LiveEntryProjectionRequest
    ) -> LiveEntryProjectionResponse:
        response = _send(self._client, _LIVE_ENTRY_PATH, encode_live_entry_request(request))
        return decode_live_entry_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxStrategyEngineLiveEntryAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class HttpxStrategyEngineOpenTradeAdapter:
    """Synchronous scalar adapter with one bounded, non-retried HTTP attempt."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = _build_client(base_url, timeout_seconds, transport)

    def project_open_trade(
        self, request: OpenTradeProjectionRequest
    ) -> OpenTradeProjectionResponse:
        response = _send(self._client, _OPEN_TRADE_PATH, encode_open_trade_request(request))
        return decode_open_trade_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxStrategyEngineOpenTradeAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _build_client(
    base_url: str, timeout_seconds: float, transport: httpx.BaseTransport | None
) -> httpx.Client:
    if type(timeout_seconds) not in {int, float}:
        raise TypeError("timeout_seconds must be a number")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")

    url = httpx.URL(base_url)
    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("base_url must be an absolute HTTP(S) URL")

    selected_transport = transport
    if selected_transport is None:
        selected_transport = httpx.HTTPTransport(retries=0)
    return httpx.Client(
        base_url=url,
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        transport=selected_transport,
    )


def _send(client: httpx.Client, path: str, body: dict[str, object]) -> httpx.Response:
    try:
        return client.post(
            path,
            json=body,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
    except httpx.TimeoutException as exc:
        raise StrategyEngineProjectionTimeout("Strategy Engine request timed out") from exc
    except httpx.TransportError as exc:
        raise StrategyEngineProjectionNetworkFailure(
            "Strategy Engine network transport failed"
        ) from exc
