"""One-shot HTTP adapter for the ABI open-position lookup endpoint."""

from types import TracebackType

import httpx

from strategy_runtime.infrastructure.abi._http_transport import (
    build_httpx_client,
    encode_opaque_path_segment,
)
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
        self._client = build_httpx_client(base_url, timeout_seconds, transport)

    def lookup(self, request: OpenPositionLookupRequest) -> OpenPositionLookupResponse:
        path = _open_position_path(request.strategy_instance_id, request.trade_cycle_id)
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


def _open_position_path(strategy_instance_id: str, trade_cycle_id: str) -> str:
    strategy_segment = encode_opaque_path_segment(strategy_instance_id)
    cycle_segment = encode_opaque_path_segment(trade_cycle_id)
    return f"/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/open-position"
