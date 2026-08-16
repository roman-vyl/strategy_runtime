from collections.abc import Callable

import httpx
import pytest

from strategy_runtime.infrastructure.abi.http_entry_cycle_recovery import (
    HttpxAbiEntryCycleRecoveryAdapter,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryNetworkFailure,
    AbiEntryCycleRecoveryProtocolError,
    AbiEntryCycleRecoveryTimeout,
    AbiEntryCycleRecoveryUnavailable,
    AbiEntryCycleRecoveryUnknownTradeCycleBinding,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import (
    EntryOrderLiveRecoveryState,
    PositionOpenRecoveryState,
    RecoveryStateAppliedEntryPackage,
    TerminalAfterFillRecoveryState,
    TerminalWithoutFillRecoveryState,
)
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageApplied,
    EntryPackageWireDesiredEntry,
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


def _applied_entry_package_body() -> dict[str, object]:
    return {
        "applied_desired_entry": {
            "side": "long",
            "source_plan_bar_open_time_ms": 900,
            "planned_entry_price": "100000",
            "initial_stop_price": "99000",
            "initial_take_price": "103000",
            "locked_exit_profile": "runner",
        },
        "calculated_quantity": "0.001",
    }


def _applied_entry_package() -> RecoveryStateAppliedEntryPackage:
    return RecoveryStateAppliedEntryPackage(
        applied_desired_entry=EntryPackageWireDesiredEntry(
            side="long",
            source_plan_bar_open_time_ms=900,
            planned_entry_price="100000",
            initial_stop_price="99000",
            initial_take_price="103000",
            locked_exit_profile="runner",
        ),
        calculated_quantity="0.001",
    )


def test_query_is_a_bodyless_get_to_the_recovery_state_path() -> None:
    fake = FakeAbi(lambda _: json_response(200, terminal_without_fill_body()))

    result = query(fake, strategy_instance_id="instance-1", trade_cycle_id="cycle-1")

    assert result == TerminalWithoutFillRecoveryState()
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "GET"
    assert (
        sent.url.raw_path
        == b"/v1/strategy-instances/instance-1/trade-cycles/cycle-1/recovery-state"
    )
    assert sent.content == b""
    assert sent.headers["accept"] == "application/json"


@pytest.mark.parametrize(
    ("trade_cycle_id", "expected_path"),
    [
        (
            "cycle/future %",
            b"/v1/strategy-instances/instance/trade-cycles/cycle%2Ffuture%20%25/recovery-state",
        ),
        (".", b"/v1/strategy-instances/instance/trade-cycles/%2E/recovery-state"),
        ("..", b"/v1/strategy-instances/instance/trade-cycles/%2E%2E/recovery-state"),
    ],
)
def test_trade_cycle_segment_is_encoded_as_one_opaque_utf8_segment(
    trade_cycle_id: str, expected_path: bytes
) -> None:
    fake = FakeAbi(lambda _: json_response(200, terminal_without_fill_body()))

    query(fake, strategy_instance_id="instance", trade_cycle_id=trade_cycle_id)

    assert fake.requests[0].url.raw_path == expected_path


def test_decodes_entry_order_live() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "recovery_state": "entry_order_live",
                "applied_entry_package": _applied_entry_package_body(),
                "first_fill_at_ms": None,
                "average_entry_price": None,
            },
        )
    )

    result = query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert result == EntryOrderLiveRecoveryState(applied_entry_package=_applied_entry_package())


def test_decodes_position_open() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "recovery_state": "position_open",
                "applied_entry_package": _applied_entry_package_body(),
                "first_fill_at_ms": 1785000012345,
                "average_entry_price": "100000",
            },
        )
    )

    result = query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert result == PositionOpenRecoveryState(
        applied_entry_package=_applied_entry_package(),
        first_fill_at_ms=1785000012345,
        average_entry_price="100000",
    )


def test_decodes_terminal_without_fill() -> None:
    fake = FakeAbi(lambda _: json_response(200, terminal_without_fill_body()))

    result = query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert result == TerminalWithoutFillRecoveryState()


def test_decodes_terminal_after_fill() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "recovery_state": "terminal_after_fill",
                "applied_entry_package": None,
                "first_fill_at_ms": None,
                "average_entry_price": None,
            },
        )
    )

    result = query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert result == TerminalAfterFillRecoveryState()


@pytest.mark.parametrize(
    "body",
    [
        {
            "recovery_state": "entry_order_live",
            "applied_entry_package": None,
            "first_fill_at_ms": None,
            "average_entry_price": None,
        },
        {
            "recovery_state": "terminal_without_fill",
            "applied_entry_package": {"anything": True},
            "first_fill_at_ms": None,
            "average_entry_price": None,
        },
        {
            "recovery_state": "position_open",
            "applied_entry_package": None,
            "first_fill_at_ms": 1,
            "average_entry_price": "1",
        },
        {
            "recovery_state": "entry_order_live",
            "applied_entry_package": None,
            "first_fill_at_ms": 1,
            "average_entry_price": None,
        },
    ],
)
def test_cross_field_invariant_violations_fail_closed(body: dict[str, object]) -> None:
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(AbiEntryCycleRecoveryProtocolError):
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")


def test_undocumented_recovery_state_value_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            200,
            {
                "recovery_state": "recovery_horizon_exceeded",
                "applied_entry_package": None,
                "first_fill_at_ms": None,
                "average_entry_price": None,
            },
        )
    )

    with pytest.raises(AbiEntryCycleRecoveryProtocolError):
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")


def test_unknown_trade_cycle_binding_is_its_own_typed_error_not_terminal() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            422,
            {
                "error": {
                    "code": "unknown_trade_cycle_binding",
                    "message": "no correlation record exists for the requested pair",
                }
            },
        )
    )

    with pytest.raises(AbiEntryCycleRecoveryUnknownTradeCycleBinding):
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")


def test_unknown_trade_cycle_binding_is_not_a_recovery_state_subtype() -> None:
    assert not issubclass(
        AbiEntryCycleRecoveryUnknownTradeCycleBinding,
        (EntryOrderLiveRecoveryState, TerminalWithoutFillRecoveryState),
    )


def test_documented_500_internal_error_is_unavailable_not_public_error() -> None:
    fake = FakeAbi(
        lambda _: json_response(500, {"error": {"code": "internal_error", "message": "boom"}})
    )

    with pytest.raises(AbiEntryCycleRecoveryUnavailable) as raised:
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert not isinstance(raised.value, AbiEntryCycleRecoveryUnknownTradeCycleBinding)


def test_undocumented_status_fails_closed() -> None:
    fake = FakeAbi(lambda _: json_response(403, {"anything": True}))

    with pytest.raises(AbiEntryCycleRecoveryProtocolError):
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")


def test_timeout_is_typed_and_not_retried() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fake = FakeAbi(timeout)

    with pytest.raises(AbiEntryCycleRecoveryTimeout):
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert len(fake.requests) == 1


def test_network_failure_is_typed_and_not_retried() -> None:
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    fake = FakeAbi(network_failure)

    with pytest.raises(AbiEntryCycleRecoveryNetworkFailure):
        query(fake, strategy_instance_id="instance", trade_cycle_id="cycle")

    assert len(fake.requests) == 1


def test_every_transport_failure_is_a_client_error_subtype() -> None:
    assert issubclass(AbiEntryCycleRecoveryTimeout, AbiEntryCycleRecoveryUnavailable) or issubclass(
        AbiEntryCycleRecoveryTimeout, AbiEntryCycleRecoveryUnavailable.__bases__[0]
    )


# ---------------------------------------------------------------------------
# The one corrective action: cancel() reuses the injected entry-package port,
# not a second HTTP transport.
# ---------------------------------------------------------------------------


class _RecordingEntryPackagePort:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[object] = []

    def send(self, request: object) -> object:
        self.requests.append(request)
        return self.result


def test_cancel_delegates_to_the_injected_entry_package_port_with_null_desired_entry() -> None:
    port = _RecordingEntryPackagePort(EntryPackageAbsent("instance", "cycle-1"))
    fake = FakeAbi(lambda _: json_response(200, terminal_without_fill_body()))

    with HttpxAbiEntryCycleRecoveryAdapter(
        base_url="http://abi.test",
        timeout_seconds=0.25,
        entry_package_port=port,  # type: ignore[arg-type]
        transport=fake.transport,
    ) as adapter:
        result = adapter.cancel("instance", "cycle-1", "BTCUSDT.P", "1")

    assert result == EntryPackageAbsent("instance", "cycle-1")
    assert len(port.requests) == 1
    sent = port.requests[0]
    assert sent.strategy_instance_id == "instance"  # type: ignore[attr-defined]
    assert sent.trade_cycle_id == "cycle-1"  # type: ignore[attr-defined]
    assert sent.ticker == "BTCUSDT.P"  # type: ignore[attr-defined]
    assert sent.desired_entry is None  # type: ignore[attr-defined]
    assert sent.risk_multiplier == "1"  # type: ignore[attr-defined]
    # cancel() never issued an HTTP request of its own -- no second transport.
    assert fake.requests == []


def test_cancel_forwards_whatever_the_entry_package_port_returns() -> None:
    applied = EntryPackageApplied(
        "instance",
        "cycle-1",
        EntryPackageWireDesiredEntry("long", 900, "1", "1", "1", "runner"),
        "1",
    )
    port = _RecordingEntryPackagePort(applied)

    with HttpxAbiEntryCycleRecoveryAdapter(
        base_url="http://abi.test",
        timeout_seconds=0.25,
        entry_package_port=port,  # type: ignore[arg-type]
        transport=httpx.MockTransport(lambda _: json_response(500, {})),
    ) as adapter:
        result = adapter.cancel("instance", "cycle-1", "BTCUSDT.P", "1")

    assert result is applied


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        HttpxAbiEntryCycleRecoveryAdapter(
            base_url="http://abi.test",
            timeout_seconds=timeout_seconds,
            entry_package_port=_RecordingEntryPackagePort(object()),  # type: ignore[arg-type]
            transport=httpx.MockTransport(lambda _: json_response(500, {})),
        )


def query(fake: FakeAbi, *, strategy_instance_id: str, trade_cycle_id: str) -> object:
    with HttpxAbiEntryCycleRecoveryAdapter(
        base_url="http://abi.test",
        timeout_seconds=0.25,
        entry_package_port=_RecordingEntryPackagePort(object()),  # type: ignore[arg-type]
        transport=fake.transport,
    ) as adapter:
        return adapter.query(strategy_instance_id, trade_cycle_id)


def terminal_without_fill_body() -> dict[str, object]:
    return {
        "recovery_state": "terminal_without_fill",
        "applied_entry_package": None,
        "first_fill_at_ms": None,
        "average_entry_price": None,
    }


def json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"content-type": "application/json; charset=utf-8"},
    )
