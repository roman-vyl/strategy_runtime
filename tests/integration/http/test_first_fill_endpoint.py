"""HTTP contract and adapter-boundary tests for the ABI first-fill endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.abi_execution_event.models import AbiFirstFillExecutionEvent
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.state.errors import StrategyInstanceStateNotFound

_PATH = "/v1/strategy-instances/{sid}/trade-cycles/{tcid}/first-fill"


def _url(sid: str = "instance-a", tcid: str = "cycle-1") -> str:
    return _PATH.format(sid=sid, tcid=tcid)


class RecordingUseCase:
    def __init__(self, result: object = None) -> None:
        self.calls: list[AbiFirstFillExecutionEvent] = []
        self._result = result

    def __call__(self, event: AbiFirstFillExecutionEvent) -> object:
        self.calls.append(event)
        return self._result


class RaisingUseCase:
    def __init__(self, error: Exception) -> None:
        self.calls: list[AbiFirstFillExecutionEvent] = []
        self._error = error

    def __call__(self, event: AbiFirstFillExecutionEvent) -> object:
        self.calls.append(event)
        raise self._error


def make_client(
    *,
    ready: bool = True,
    process_first_fill: Any = None,
) -> TestClient:
    app = create_http_app(
        ready=ready,
        trace_id_factory=lambda: "trace-1",
        process_committed_bar=None,
        process_first_fill=process_first_fill,
    )
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 4.1 / 4.2: method and path
# ---------------------------------------------------------------------------


def test_route_method_is_put_and_path_is_exact() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 200
    assert len(recorder.calls) == 1
    assert recorder.calls[0].strategy_instance_id == "instance-a"
    assert recorder.calls[0].trade_cycle_id == "cycle-1"

    # A POST to the identical path is not the registered method.
    post_response = client.post(_url(), json={"first_fill_at_ms": 1})
    assert post_response.status_code == 405


# ---------------------------------------------------------------------------
# 4.3: body carries only first_fill_at_ms
# ---------------------------------------------------------------------------


def test_body_with_only_first_fill_at_ms_is_accepted() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 200


def test_duplicating_path_identifiers_in_body_is_rejected_as_extra_fields() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(
        _url(),
        json={
            "first_fill_at_ms": 1,
            "strategy_instance_id": "instance-a",
            "trade_cycle_id": "cycle-1",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "invalid_webhook"}
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# 4.4 / 4.5 / 4.14: success and identical-retry response
# ---------------------------------------------------------------------------


def test_first_successful_call_returns_200_first_fill_recorded() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 200
    assert response.json() == {"status": "first_fill_recorded"}


def test_identical_retry_returns_identical_response() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    first = client.put(_url(), json={"first_fill_at_ms": 1})
    second = client.put(_url(), json={"first_fill_at_ms": 1})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"status": "first_fill_recorded"}
    assert len(recorder.calls) == 2


def test_success_response_contains_only_status_field() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.json() == {"status": "first_fill_recorded"}
    assert set(response.json().keys()) == {"status"}


# ---------------------------------------------------------------------------
# 4.6: response only after the callable returns
# ---------------------------------------------------------------------------


def test_response_is_only_returned_after_callable_completes() -> None:
    order: list[str] = []

    def use_case(_event: AbiFirstFillExecutionEvent) -> object:
        order.append("callable_returned_before_response")
        return object()

    client = make_client(process_first_fill=use_case)
    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 200
    assert order == ["callable_returned_before_response"]


# ---------------------------------------------------------------------------
# 4.7: no BackgroundTasks
# ---------------------------------------------------------------------------


def test_background_tasks_add_task_is_never_called(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    original_add_task = BackgroundTasks.add_task

    def spying_add_task(self: BackgroundTasks, *args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        return original_add_task(self, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", spying_add_task)

    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 200
    assert calls == []


# ---------------------------------------------------------------------------
# 4.8: body-shape rejection cases -> 400
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"first_fill_at_ms": True},
        {"first_fill_at_ms": 1.0},
        {"first_fill_at_ms": "1"},
        {"first_fill_at_ms": 0},
        {"first_fill_at_ms": -1},
        {},
        {"first_fill_at_ms": 1, "extra": "field"},
    ],
    ids=[
        "bool",
        "float",
        "string",
        "zero",
        "negative",
        "missing",
        "extra_field",
    ],
)
def test_invalid_body_shapes_return_400(payload: dict[str, object]) -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), json=payload)

    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "invalid_webhook"}
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# 4.9 / 4.10: typed exceptions -> 404 / 409
# ---------------------------------------------------------------------------


def test_strategy_instance_state_not_found_returns_404() -> None:
    use_case = RaisingUseCase(StrategyInstanceStateNotFound("instance-a"))
    client = make_client(process_first_fill=use_case)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 404
    assert response.json() == {"status": "strategy_instance_state_not_found"}


def test_first_fill_invariant_error_returns_409() -> None:
    use_case = RaisingUseCase(FirstFillInvariantError("already frozen"))
    client = make_client(process_first_fill=use_case)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 409
    assert response.json() == {"status": "first_fill_conflict"}


# ---------------------------------------------------------------------------
# 4.11: not-ready -> 503
# ---------------------------------------------------------------------------


def test_not_ready_application_returns_503_without_invoking_callable() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(ready=False, process_first_fill=recorder)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert recorder.calls == []


def test_ready_but_unconnected_callable_returns_503() -> None:
    client = make_client(ready=True, process_first_fill=None)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


# ---------------------------------------------------------------------------
# 4.12 / 4.13: unexpected exception and internal alignment ValueError -> 500
# ---------------------------------------------------------------------------


def test_unexpected_exception_returns_500() -> None:
    use_case = RaisingUseCase(RuntimeError("repository failure"))
    client = make_client(process_first_fill=use_case)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


def test_internal_alignment_value_error_returns_500_not_400() -> None:
    use_case = RaisingUseCase(ValueError("unsupported base_timeframe"))
    client = make_client(process_first_fill=use_case)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}


# ---------------------------------------------------------------------------
# 4.16: path-identifier round-trip (normal / unicode / whitespace / percent)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_id",
    [
        "strategy-42",
        "стратегия-1",
        "has space",
        "100%",
    ],
    ids=["normal", "unicode", "whitespace", "percent"],
)
def test_path_identifiers_round_trip_unchanged(raw_id: str) -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(sid=raw_id, tcid=raw_id), json={"first_fill_at_ms": 1})

    assert response.status_code == 200
    assert len(recorder.calls) == 1
    assert recorder.calls[0].strategy_instance_id == raw_id
    assert recorder.calls[0].trade_cycle_id == raw_id


# ---------------------------------------------------------------------------
# 4.17: media-type handling -> 400, never 415
# ---------------------------------------------------------------------------


def test_missing_content_type_returns_400_not_415() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(_url(), content='{"first_fill_at_ms": 1}')

    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "invalid_webhook"}
    assert recorder.calls == []


def test_wrong_content_type_returns_400_not_415() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(
        _url(),
        content='{"first_fill_at_ms": 1}',
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "invalid_webhook"}
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# 4.18: Accept header is not validated -> no 406
# ---------------------------------------------------------------------------


def test_accept_header_does_not_change_response_status() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(
        _url(),
        json={"first_fill_at_ms": 1},
        headers={"accept": "text/plain"},
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 5.1 / 5.2: adapter constructs the event exactly, calls the callable exactly once
# ---------------------------------------------------------------------------


def test_adapter_constructs_event_from_path_and_body_unmodified() -> None:
    recorder = RecordingUseCase(result=object())
    client = make_client(process_first_fill=recorder)

    response = client.put(
        "/v1/strategy-instances/inst-99/trade-cycles/cyc-7/first-fill",
        json={"first_fill_at_ms": 42},
    )

    assert response.status_code == 200
    assert len(recorder.calls) == 1
    event = recorder.calls[0]
    assert event.strategy_instance_id == "inst-99"
    assert event.trade_cycle_id == "cyc-7"
    assert event.first_fill_at_ms == 42


def test_adapter_calls_callable_exactly_once_even_when_it_errors() -> None:
    use_case = RaisingUseCase(RuntimeError("boom"))
    client = make_client(process_first_fill=use_case)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 500
    assert len(use_case.calls) == 1


# ---------------------------------------------------------------------------
# 5.4: known exception types map to their exact documented status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_body"),
    [
        (
            StrategyInstanceStateNotFound("instance-a"),
            404,
            {"status": "strategy_instance_state_not_found"},
        ),
        (
            FirstFillInvariantError("conflict"),
            409,
            {"status": "first_fill_conflict"},
        ),
    ],
)
def test_known_exception_types_map_to_exact_typed_response(
    error: Exception, expected_status: int, expected_body: dict[str, str]
) -> None:
    use_case = RaisingUseCase(error)
    client = make_client(process_first_fill=use_case)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == expected_status
    assert response.json() == expected_body


# ---------------------------------------------------------------------------
# 5.5: unknown exceptions are logged and produce 500
# ---------------------------------------------------------------------------


def test_unknown_exception_is_logged_and_returns_500() -> None:
    import logging
    from unittest.mock import MagicMock

    fake_logger = MagicMock(spec=logging.Logger)
    use_case = RaisingUseCase(RuntimeError("boom"))
    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        process_committed_bar=None,
        process_first_fill=use_case,
        logger=fake_logger,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.put(_url(), json={"first_fill_at_ms": 1})

    assert response.status_code == 500
    assert response.json() == {"status": "internal_error"}
    fake_logger.exception.assert_called_once()
