"""One-shot HTTP adapter for the ABI open-position lookup endpoint."""

import math
from types import TracebackType
from urllib.parse import quote

import httpx

from strategy_runtime.infrastructure.abi.open_position_codec import (
    decode_open_position_response,
)
from strategy_runtime.runtime.open_position.errors import (
    OpenPositionLookupNetworkFailure,
    OpenPositionLookupTimeout,
)
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupRequest,
    OpenPositionLookupResponse,
)


class HttpxAbiOpenPositionLookupAdapter:
    """Synchronous scalar adapter with one bounded, non-retried HTTP attempt."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
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
        self._client = httpx.Client(
            base_url=url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            transport=selected_transport,
        )

    def lookup(self, request: OpenPositionLookupRequest) -> OpenPositionLookupResponse:
        path = _open_position_path(request.strategy_instance_id)
        try:
            response = self._client.get(path, headers={"accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise OpenPositionLookupTimeout("ABI open-position lookup request timed out") from exc
        except httpx.TransportError as exc:
            raise OpenPositionLookupNetworkFailure(
                "ABI open-position lookup network transport failed"
            ) from exc

        return decode_open_position_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxAbiOpenPositionLookupAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _open_position_path(strategy_instance_id: str) -> str:
    segment = _encode_opaque_path_segment(strategy_instance_id)
    return f"/v1/strategy-instances/{segment}/open-position"


def _encode_opaque_path_segment(value: str) -> str:
    encoded = quote(value, safe="", encoding="utf-8", errors="strict")
    if value in {".", ".."}:
        return encoded.replace(".", "%2E")
    return encoded
