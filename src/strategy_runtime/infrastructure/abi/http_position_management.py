"""One-shot HTTP adapter for the ABI position-management endpoints."""

import math
from types import TracebackType
from urllib.parse import quote

import httpx

from strategy_runtime.infrastructure.abi.position_management_codec import (
    decode_apply_protection_response,
    decode_close_position_response,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionNetworkFailure,
    PositionManagementExecutionTimeout,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)


class HttpxAbiPositionManagementAdapter:
    """Synchronous `PositionManagementExecutionPort` with one bounded, non-retried attempt."""

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

    def apply_protection(self, command: ApplyProtectionCommand) -> ProtectionAppliedConfirmation:
        path = _protection_path(command.strategy_instance_id, command.trade_cycle_id)
        body = {
            "stop_price": command.desired_protection.stop_price,
            "take_price": command.desired_protection.take_price,
        }
        try:
            response = self._client.put(
                path,
                json=body,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise PositionManagementExecutionTimeout(
                "ABI apply_protection request timed out"
            ) from exc
        except httpx.TransportError as exc:
            raise PositionManagementExecutionNetworkFailure(
                "ABI apply_protection network transport failed"
            ) from exc

        return decode_apply_protection_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
            command=command,
        )

    def close_position(self, command: ClosePositionCommand) -> PositionClosedConfirmation:
        path = _open_position_path(command.strategy_instance_id, command.trade_cycle_id)
        try:
            response = self._client.delete(path, headers={"accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise PositionManagementExecutionTimeout(
                "ABI close_position request timed out"
            ) from exc
        except httpx.TransportError as exc:
            raise PositionManagementExecutionNetworkFailure(
                "ABI close_position network transport failed"
            ) from exc

        return decode_close_position_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
            command=command,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxAbiPositionManagementAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _protection_path(strategy_instance_id: str, trade_cycle_id: str) -> str:
    strategy_segment = _encode_opaque_path_segment(strategy_instance_id)
    cycle_segment = _encode_opaque_path_segment(trade_cycle_id)
    return f"/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/protection"


def _open_position_path(strategy_instance_id: str, trade_cycle_id: str) -> str:
    strategy_segment = _encode_opaque_path_segment(strategy_instance_id)
    cycle_segment = _encode_opaque_path_segment(trade_cycle_id)
    return f"/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/open-position"


def _encode_opaque_path_segment(value: str) -> str:
    encoded = quote(value, safe="", encoding="utf-8", errors="strict")
    if value in {".", ".."}:
        return encoded.replace(".", "%2E")
    return encoded
