import json
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest

from strategy_runtime.runtime.abi.entry_package_errors import (
    AbiEntryPackageNetworkFailure,
    AbiEntryPackageProtocolError,
    AbiEntryPackageTimeout,
)
from strategy_runtime.runtime.abi.entry_package_http import HttpxAbiEntryPackageAdapter
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageApplied,
    EntryPackageInternalError,
    EntryPackageMalformedJson,
    EntryPackageRequest,
    EntryPackageUnsupportedMediaType,
    EntryPackageValidationFailed,
    EntryPackageWireDesiredEntry,
)

ResponseFactory = Callable[[httpx.Request], httpx.Response]
_DEFAULT_DESIRED_ENTRY = object()


class FakeAbi:
    def __init__(self, response_factory: ResponseFactory) -> None:
        self.requests: list[httpx.Request] = []
        self._response_factory = response_factory
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response_factory(request)


def test_present_request_preserves_raw_path_body_and_decimal_lexemes() -> None:
    request = make_request(
        strategy_instance_id="instance/future %",
        trade_cycle_id="цикл id",
        desired_entry=make_desired_entry(),
        risk_multiplier="+000.2500e1",
    )
    fake = FakeAbi(lambda _: json_response(200, applied_body(request)))

    result = send(fake, request)

    assert isinstance(result, EntryPackageApplied)
    assert result.applied_desired_entry.planned_entry_price == "-001.2300e+2"
    assert result.calculated_quantity == "0.00100"
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.method == "PUT"
    assert sent.url.raw_path == (
        b"/v1/strategy-instances/instance%2Ffuture%20%25"
        b"/trade-cycles/%D1%86%D0%B8%D0%BA%D0%BB%20id/entry-package"
    )
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["accept"] == "application/json"
    assert json.loads(sent.content) == {
        "ticker": "BTCUSDT.P",
        "desired_entry": desired_entry_body(request.desired_entry),
        "risk_multiplier": "+000.2500e1",
    }


@pytest.mark.parametrize(
    ("strategy_instance_id", "trade_cycle_id", "expected_path"),
    [
        (
            ".",
            "..",
            b"/v1/strategy-instances/%2E/trade-cycles/%2E%2E/entry-package",
        ),
        (
            "%",
            "/",
            b"/v1/strategy-instances/%25/trade-cycles/%2F/entry-package",
        ),
    ],
)
def test_path_segments_are_encoded_without_url_normalization(
    strategy_instance_id: str,
    trade_cycle_id: str,
    expected_path: bytes,
) -> None:
    request = make_request(
        strategy_instance_id=strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        desired_entry=None,
    )
    fake = FakeAbi(lambda _: json_response(200, absent_body(request)))

    result = send(fake, request)

    assert isinstance(result, EntryPackageAbsent)
    assert fake.requests[0].url.raw_path == expected_path


def test_absence_request_sends_non_null_risk_multiplier() -> None:
    request = make_request(desired_entry=None, risk_multiplier="+01.00")
    fake = FakeAbi(lambda _: json_response(200, absent_body(request)))

    result = send(fake, request)

    assert result == EntryPackageAbsent(
        strategy_instance_id=request.strategy_instance_id,
        trade_cycle_id=request.trade_cycle_id,
    )
    assert json.loads(fake.requests[0].content) == {
        "ticker": "BTCUSDT.P",
        "desired_entry": None,
        "risk_multiplier": "+01.00",
    }


@pytest.mark.parametrize(
    ("status_code", "body", "result_type"),
    [
        (
            400,
            {"error": {"code": "malformed_json", "message": "bad json"}},
            EntryPackageMalformedJson,
        ),
        (
            415,
            {
                "error": {
                    "code": "unsupported_media_type",
                    "message": "json required",
                }
            },
            EntryPackageUnsupportedMediaType,
        ),
        (
            500,
            {"error": {"code": "internal_error", "message": "internal error"}},
            EntryPackageInternalError,
        ),
    ],
)
def test_public_errors_map_to_typed_results(
    status_code: int, body: dict[str, object], result_type: type[object]
) -> None:
    request = make_request()
    fake = FakeAbi(lambda _: json_response(status_code, body))

    result = send(fake, request)

    assert isinstance(result, result_type)
    assert result.message == body["error"]["message"]  # type: ignore[index,union-attr]
    assert len(fake.requests) == 1


def test_validation_failure_preserves_closed_details() -> None:
    request = make_request()
    details = [
        {"path": "/risk_multiplier", "message": "must be positive"},
        {"path": "", "message": ""},
    ]
    fake = FakeAbi(
        lambda _: json_response(
            422,
            {
                "error": {
                    "code": "validation_failed",
                    "message": "request validation failed",
                    "details": details,
                }
            },
        )
    )

    result = send(fake, request)

    assert isinstance(result, EntryPackageValidationFailed)
    assert [(detail.path, detail.message) for detail in result.details] == [
        ("/risk_multiplier", "must be positive"),
        ("", ""),
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"extra": True}),
        lambda body: body.pop("calculated_quantity"),
        lambda body: body.update({"calculated_quantity": 0.001}),
        lambda body: body.update({"accepted_risk_multiplier": "0"}),
        lambda body: body.update({"status": "other"}),
        lambda body: body["applied_desired_entry"].update({"extra": True}),
        lambda body: body["applied_desired_entry"].update({"source_plan_bar_open_time_ms": True}),
        lambda body: body["applied_desired_entry"].update({"initial_take_price": "0"}),
    ],
)
def test_malformed_applied_success_fails_closed(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    request = make_request()
    body = applied_body(request)
    mutate(body)
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, request)

    assert len(fake.requests) == 1


@pytest.mark.parametrize("field", ["strategy_instance_id", "trade_cycle_id"])
def test_success_identifier_mismatch_fails_closed(field: str) -> None:
    request = make_request()
    body = applied_body(request)
    body[field] = "different"
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, request)


def test_undocumented_2xx_does_not_acknowledge() -> None:
    request = make_request()
    fake = FakeAbi(lambda _: json_response(201, applied_body(request)))

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, request)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {
            "strategy_instance_id": "instance",
            "trade_cycle_id": "cycle",
            "status": "entry_package_absent",
            "extra": True,
        },
        {
            "strategy_instance_id": "different",
            "trade_cycle_id": "cycle",
            "status": "entry_package_absent",
        },
    ],
)
def test_malformed_or_mismatched_absent_success_fails_closed(body: object) -> None:
    fake = FakeAbi(lambda _: json_response(200, body))

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, make_request(desired_entry=None))


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, []),
        (
            400,
            {
                "error": {"code": "malformed_json", "message": "bad"},
                "extra": True,
            },
        ),
        (400, {"error": {"code": "internal_error", "message": "wrong pair"}}),
        (
            422,
            {
                "error": {
                    "code": "validation_failed",
                    "message": "missing details",
                }
            },
        ),
        (
            422,
            {
                "error": {
                    "code": "validation_failed",
                    "message": "empty details",
                    "details": [],
                }
            },
        ),
        (
            500,
            {
                "error": {
                    "code": "internal_error",
                    "message": "unexpected details",
                    "details": [{"path": "/", "message": "no"}],
                }
            },
        ),
        (
            415,
            {
                "error": {
                    "code": "unsupported_media_type",
                    "message": "",
                }
            },
        ),
        (
            400,
            {
                "error": {
                    "code": "malformed_json",
                    "message": "bad",
                    "extra": True,
                }
            },
        ),
        (
            422,
            {
                "error": {
                    "code": "validation_failed",
                    "message": "bad detail",
                    "details": [{"path": "/", "message": "bad", "extra": True}],
                }
            },
        ),
    ],
)
def test_invalid_public_error_envelope_fails_closed(
    status_code: int, body: dict[str, object]
) -> None:
    fake = FakeAbi(lambda _: json_response(status_code, body))

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, make_request())


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
            content=b"{}",
            headers={"content-type": "application/json; profile=test"},
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
            content=b'{"status":"entry_package_absent","status":"entry_package_absent"}',
            headers={"content-type": "application/json"},
        ),
    ],
)
def test_invalid_content_type_utf8_or_json_fails_closed(response: httpx.Response) -> None:
    fake = FakeAbi(lambda _: response)

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, make_request())

    assert len(fake.requests) == 1


def test_timeout_is_typed_and_not_retried() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fake = FakeAbi(timeout)

    with pytest.raises(AbiEntryPackageTimeout):
        send(fake, make_request())

    assert len(fake.requests) == 1


def test_network_failure_is_typed_and_not_retried() -> None:
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    fake = FakeAbi(network_failure)

    with pytest.raises(AbiEntryPackageNetworkFailure):
        send(fake, make_request())

    assert len(fake.requests) == 1


def test_programming_failure_is_not_relabelled() -> None:
    def programming_failure(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug")

    fake = FakeAbi(programming_failure)

    with pytest.raises(RuntimeError, match="bug"):
        send(fake, make_request())

    assert len(fake.requests) == 1


def test_redirect_is_not_followed_and_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: httpx.Response(
            307,
            headers={
                "location": "http://other.test/target",
                "content-type": "application/json",
            },
            json={"error": {"code": "internal_error", "message": "redirect"}},
        )
    )

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, make_request())

    assert len(fake.requests) == 1


def test_undocumented_status_fails_closed() -> None:
    fake = FakeAbi(
        lambda _: json_response(
            503,
            {"error": {"code": "internal_error", "message": "unavailable"}},
        )
    )

    with pytest.raises(AbiEntryPackageProtocolError):
        send(fake, make_request())

    assert len(fake.requests) == 1


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        HttpxAbiEntryPackageAdapter(
            base_url="http://abi.test",
            timeout_seconds=timeout_seconds,
            transport=httpx.MockTransport(lambda _: json_response(500, {})),
        )


def send(fake: FakeAbi, request: EntryPackageRequest) -> object:
    with HttpxAbiEntryPackageAdapter(
        base_url="http://abi.test",
        timeout_seconds=0.25,
        transport=fake.transport,
    ) as adapter:
        return adapter.send(request)


def make_request(
    *,
    strategy_instance_id: str = "instance",
    trade_cycle_id: str = "cycle",
    desired_entry: object = _DEFAULT_DESIRED_ENTRY,
    risk_multiplier: str = "1",
) -> EntryPackageRequest:
    desired_entry_value = (
        make_desired_entry()
        if desired_entry is _DEFAULT_DESIRED_ENTRY
        else cast("EntryPackageWireDesiredEntry | None", desired_entry)
    )
    return EntryPackageRequest(
        strategy_instance_id=strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        ticker="BTCUSDT.P",
        desired_entry=desired_entry_value,
        risk_multiplier=risk_multiplier,
    )


def make_desired_entry() -> EntryPackageWireDesiredEntry:
    return EntryPackageWireDesiredEntry(
        side="long",
        source_plan_bar_open_time_ms=1785000000000,
        planned_entry_price="-001.2300e+2",
        initial_stop_price="+999.00",
        initial_take_price="000.10e1",
        locked_exit_profile="",
    )


def desired_entry_body(
    desired_entry: EntryPackageWireDesiredEntry | None,
) -> dict[str, object] | None:
    if desired_entry is None:
        return None
    return {
        "side": desired_entry.side,
        "source_plan_bar_open_time_ms": desired_entry.source_plan_bar_open_time_ms,
        "planned_entry_price": desired_entry.planned_entry_price,
        "initial_stop_price": desired_entry.initial_stop_price,
        "initial_take_price": desired_entry.initial_take_price,
        "locked_exit_profile": desired_entry.locked_exit_profile,
    }


def applied_body(request: EntryPackageRequest) -> dict[str, Any]:
    return {
        "strategy_instance_id": request.strategy_instance_id,
        "trade_cycle_id": request.trade_cycle_id,
        "status": "entry_package_applied",
        "applied_desired_entry": desired_entry_body(request.desired_entry),
        "calculated_quantity": "0.00100",
    }


def absent_body(request: EntryPackageRequest) -> dict[str, object]:
    return {
        "strategy_instance_id": request.strategy_instance_id,
        "trade_cycle_id": request.trade_cycle_id,
        "status": "entry_package_absent",
    }


def json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"content-type": "application/json; charset=utf-8"},
    )
