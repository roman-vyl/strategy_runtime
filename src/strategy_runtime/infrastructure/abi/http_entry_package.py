"""One-shot HTTP adapter for the ABI desired-entry-package endpoint."""

from types import TracebackType

import httpx

from strategy_runtime.infrastructure.abi._http_transport import (
    build_httpx_client,
    encode_opaque_path_segment,
)
from strategy_runtime.runtime.abi.entry_package_codec import (
    decode_entry_package_response,
    encode_entry_package_request,
)
from strategy_runtime.runtime.abi.entry_package_errors import (
    AbiEntryPackageNetworkFailure,
    AbiEntryPackageTimeout,
)
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageRequest,
    EntryPackageResult,
)


class HttpxAbiEntryPackageAdapter:
    """Synchronous scalar adapter with one bounded, non-retried HTTP attempt."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = build_httpx_client(base_url, timeout_seconds, transport)

    def send(self, request: EntryPackageRequest) -> EntryPackageResult:
        path = _entry_package_path(request.strategy_instance_id, request.trade_cycle_id)
        try:
            response = self._client.put(
                path,
                json=encode_entry_package_request(request),
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise AbiEntryPackageTimeout("ABI entry-package request timed out") from exc
        except httpx.TransportError as exc:
            raise AbiEntryPackageNetworkFailure(
                "ABI entry-package network transport failed"
            ) from exc

        return decode_entry_package_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
            request=request,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxAbiEntryPackageAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _entry_package_path(strategy_instance_id: str, trade_cycle_id: str) -> str:
    strategy_segment = encode_opaque_path_segment(strategy_instance_id)
    cycle_segment = encode_opaque_path_segment(trade_cycle_id)
    return f"/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/entry-package"
