import queue

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.committed_bar_intake import CommittedBarIntakeBoundary
from strategy_runtime.utility.committed_bar import CommittedBarEvent


class RecordingLogger:
    """A minimal stand-in for `logging.Logger` that records structured calls."""

    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, object]]] = []
        self.error_calls: list[tuple[str, dict[str, object]]] = []
        self.exception_calls: list[str] = []

    def warning(self, message: str, *, extra: dict[str, object] | None = None) -> None:
        self.warning_calls.append((message, extra or {}))

    def error(self, message: str, *, extra: dict[str, object] | None = None) -> None:
        self.error_calls.append((message, extra or {}))

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self.exception_calls.append(message)


def make_client(
    *,
    ready: bool = True,
    capacity: int = 8,
    ids: list[str] | None = None,
    logger: RecordingLogger | None = None,
) -> tuple[TestClient, CommittedBarIntakeBoundary | None, RecordingLogger]:
    intake = CommittedBarIntakeBoundary(capacity) if ready else None
    values = iter(ids or ["flow-1", "flow-2"])
    recording_logger = logger or RecordingLogger()
    app = create_http_app(
        ready=ready,
        trace_id_factory=lambda: next(values),
        committed_bar_intake=intake,
        process_first_fill=None,
        logger=recording_logger,  # type: ignore[arg-type]
    )
    return TestClient(app), intake, recording_logger


def test_health_endpoints_when_ready() -> None:
    client, _, _ = make_client()
    assert client.get("/health/live").json() == {"status": "live"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_not_ready_health_and_webhook() -> None:
    client, _, _ = make_client(ready=False)
    assert client.get("/health/live").status_code == 200
    ready_response = client.get("/health/ready")
    assert ready_response.status_code == 503
    assert ready_response.json() == {"status": "not_ready"}
    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_accepts_required_fields_and_ignores_unknown_fields() -> None:
    client, intake, _ = make_client()
    response = client.post(
        "/v1/webhooks/closed-bar",
        json={
            "instrument": "BTCUSDT.P",
            "timeframe": "5m",
            "open_time_ms": 123,
            "future_field": {"ignored": True},
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert intake is not None
    assert intake.get(timeout=1) == CommittedBarEvent("BTCUSDT.P", "5m", 123)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"instrument": "", "timeframe": "5m", "open_time_ms": 1},
        {"instrument": "BTCUSDT.P", "timeframe": " ", "open_time_ms": 1},
        {"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": -1},
        {"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": "1"},
        {"instrument": 7, "timeframe": "5m", "open_time_ms": 1},
        ["not", "an", "object"],
    ],
)
def test_invalid_payloads_return_400(payload: object) -> None:
    client, intake, _ = make_client()
    response = client.post("/v1/webhooks/closed-bar", json=payload)
    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "invalid_webhook"}
    assert intake is not None
    with pytest.raises(queue.Empty):
        intake.get(timeout=0)


def test_malformed_json_returns_400() -> None:
    client, intake, _ = make_client()
    response = client.post(
        "/v1/webhooks/closed-bar",
        content="{broken",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert intake is not None
    with pytest.raises(queue.Empty):
        intake.get(timeout=0)


def test_separate_requests_generate_and_discard_separate_trace_ids() -> None:
    generated: list[str] = []
    values = iter(["trace-a", "trace-b"])

    def trace_id_factory() -> str:
        value = next(values)
        generated.append(value)
        return value

    intake = CommittedBarIntakeBoundary(8)
    app = create_http_app(
        ready=True,
        trace_id_factory=trace_id_factory,
        committed_bar_intake=intake,
        process_first_fill=None,
    )
    client = TestClient(app)
    payload = {"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1}
    assert client.post("/v1/webhooks/closed-bar", json=payload).status_code == 200
    assert client.post("/v1/webhooks/closed-bar", json=payload).status_code == 200
    assert generated == ["trace-a", "trace-b"]
    assert intake.get(timeout=1) == CommittedBarEvent("BTCUSDT.P", "5m", 1)
    assert intake.get(timeout=1) == CommittedBarEvent("BTCUSDT.P", "5m", 1)
    with pytest.raises(queue.Empty):
        intake.get(timeout=0)


def test_unexpected_pre_acceptance_failure_returns_500() -> None:
    intake = CommittedBarIntakeBoundary(8)
    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        committed_bar_intake=intake,
        process_first_fill=None,
    )
    client = TestClient(app)
    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )
    assert response.status_code == 500
    assert response.json() == {"status": "error"}
    with pytest.raises(queue.Empty):
        intake.get(timeout=0)


def test_valid_request_returns_200_before_any_processing_occurs() -> None:
    """5.1: acceptance means "enqueued," not "processed" -- no orchestrator
    call, no worker, is ever touched by the HTTP layer itself."""
    intake = CommittedBarIntakeBoundary(8)
    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        committed_bar_intake=intake,
        process_first_fill=None,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    # The event is sitting in the boundary, untouched by any consumer.
    assert intake.get(timeout=1) == CommittedBarEvent("BTCUSDT.P", "5m", 1)


def test_full_queue_returns_503_creates_no_processing_work_and_logs_queue_full() -> None:
    logger = RecordingLogger()
    client, intake, logger = make_client(capacity=1, logger=logger)
    assert intake is not None

    first = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "ETHUSDT.P", "timeframe": "5m", "open_time_ms": 2},
    )

    assert second.status_code == 503
    assert second.json() == {"status": "not_ready"}
    # Only the first event ever reached the queue.
    assert intake.get(timeout=1) == CommittedBarEvent("BTCUSDT.P", "5m", 1)
    with pytest.raises(queue.Empty):
        intake.get(timeout=0)

    assert len(logger.error_calls) == 1
    message, extra = logger.error_calls[0]
    assert "queue_full" in message
    assert extra["instrument"] == "ETHUSDT.P"
    assert extra["timeframe"] == "5m"
    assert extra["open_time_ms"] == 2
    assert extra["capacity"] == 1
    assert logger.warning_calls == []


def test_intake_stopping_returns_503_does_not_enqueue_and_logs_intake_stopping() -> None:
    logger = RecordingLogger()
    client, intake, logger = make_client(capacity=8, logger=logger)
    assert intake is not None
    intake.stop_accepting()

    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    with pytest.raises(queue.Empty):
        intake.get(timeout=0)

    assert len(logger.warning_calls) == 1
    message, extra = logger.warning_calls[0]
    assert "intake_stopping" in message
    assert extra["instrument"] == "BTCUSDT.P"
    assert extra["timeframe"] == "5m"
    assert extra["open_time_ms"] == 1
    assert logger.error_calls == []
