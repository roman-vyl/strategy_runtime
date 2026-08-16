"""One-shot HTTP adapter for the ABI entry-cycle recovery-state endpoint."""

from types import TracebackType

import httpx

from strategy_runtime.infrastructure.abi._http_transport import (
    build_httpx_client,
    encode_opaque_path_segment,
)
from strategy_runtime.infrastructure.abi.entry_cycle_recovery_codec import (
    decode_recovery_state_response,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryNetworkFailure,
    AbiEntryCycleRecoveryTimeout,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import RecoveryStateResponse
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageRequest,
    EntryPackageResult,
)
from strategy_runtime.runtime.abi.entry_package_ports import AbiEntryPackagePort


class HttpxAbiEntryCycleRecoveryAdapter:
    """Synchronous scalar adapter: one bounded GET, plus a reused entry-package CANCEL.

    The corrective CANCEL is not a second HTTP transport: it is delegated to
    the same production `AbiEntryPackagePort` used by ordinary entry
    reconciliation, exactly as the paired capability requires.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        entry_package_port: AbiEntryPackagePort,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = build_httpx_client(base_url, timeout_seconds, transport)
        self._entry_package_port = entry_package_port

    def query(self, strategy_instance_id: str, trade_cycle_id: str) -> RecoveryStateResponse:
        path = _recovery_state_path(strategy_instance_id, trade_cycle_id)
        try:
            response = self._client.get(path, headers={"accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise AbiEntryCycleRecoveryTimeout(
                "ABI entry-cycle recovery-state request timed out"
            ) from exc
        except httpx.TransportError as exc:
            raise AbiEntryCycleRecoveryNetworkFailure(
                "ABI entry-cycle recovery-state network transport failed"
            ) from exc

        return decode_recovery_state_response(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            content=response.content,
        )

    def cancel(
        self,
        strategy_instance_id: str,
        trade_cycle_id: str,
        ticker: str,
        risk_multiplier: str,
    ) -> EntryPackageResult:
        request = EntryPackageRequest(
            strategy_instance_id=strategy_instance_id,
            trade_cycle_id=trade_cycle_id,
            ticker=ticker,
            desired_entry=None,
            risk_multiplier=risk_multiplier,
        )
        return self._entry_package_port.send(request)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxAbiEntryCycleRecoveryAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _recovery_state_path(strategy_instance_id: str, trade_cycle_id: str) -> str:
    strategy_segment = encode_opaque_path_segment(strategy_instance_id)
    cycle_segment = encode_opaque_path_segment(trade_cycle_id)
    return (
        f"/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/recovery-state"
    )
