import json

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.utility.committed_bar import CommittedBarEvent


class RecordingUseCase:
    def __init__(self) -> None:
        self.calls: list[CommittedBarEvent] = []

    def __call__(self, notification: CommittedBarEvent) -> None:
        self.calls.append(notification)


def make_client(
    *,
    ready: bool = True,
    use_case: RecordingUseCase | None = None,
    ids: list[str] | None = None,
) -> tuple[TestClient, RecordingUseCase]:
    recorder = use_case or RecordingUseCase()
    values = iter(ids or ["flow-1", "flow-2"])
    app = create_http_app(
        ready=ready,
        trace_id_factory=lambda: next(values),
        process_committed_bar=recorder if ready else None,
    )
    return TestClient(app), recorder


def test_health_endpoints_when_ready() -> None:
    client, _ = make_client()
    assert client.get("/health/live").json() == {"status": "live"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_not_ready_health_and_webhook() -> None:
    client, recorder = make_client(ready=False)
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
    assert recorder.calls == []


def test_accepts_required_fields_and_ignores_unknown_fields() -> None:
    client, recorder = make_client()
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
    assert recorder.calls == [CommittedBarEvent("BTCUSDT.P", "5m", 123)]


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
    client, recorder = make_client()
    response = client.post("/v1/webhooks/closed-bar", json=payload)
    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "invalid_webhook"}
    assert recorder.calls == []


def test_malformed_json_returns_400() -> None:
    client, recorder = make_client()
    response = client.post(
        "/v1/webhooks/closed-bar",
        content="{broken",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert recorder.calls == []


def test_separate_requests_generate_and_discard_separate_trace_ids() -> None:
    generated: list[str] = []
    values = iter(["trace-a", "trace-b"])

    def trace_id_factory() -> str:
        value = next(values)
        generated.append(value)
        return value

    recorder = RecordingUseCase()
    app = create_http_app(
        ready=True,
        trace_id_factory=trace_id_factory,
        process_committed_bar=recorder,
    )
    client = TestClient(app)
    payload = {"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1}
    assert client.post("/v1/webhooks/closed-bar", json=payload).status_code == 200
    assert client.post("/v1/webhooks/closed-bar", json=payload).status_code == 200
    assert generated == ["trace-a", "trace-b"]
    assert recorder.calls == [
        CommittedBarEvent("BTCUSDT.P", "5m", 1),
        CommittedBarEvent("BTCUSDT.P", "5m", 1),
    ]


def test_unexpected_pre_acceptance_failure_returns_500() -> None:
    recorder = RecordingUseCase()
    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        process_committed_bar=recorder,
    )
    client = TestClient(app)
    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )
    assert response.status_code == 500
    assert response.json() == {"status": "error"}
    assert recorder.calls == []


def test_background_failure_does_not_change_acknowledgement() -> None:
    def failing_use_case(_notification: CommittedBarEvent) -> None:
        raise RuntimeError("background failed")

    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        process_committed_bar=failing_use_case,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_acknowledgement_is_sent_before_background_task_completes() -> None:
    import anyio

    background_started = anyio.Event()
    release_background = anyio.Event()
    response_sent = anyio.Event()
    messages: list[dict[str, object]] = []

    async def blocking_use_case(_notification: CommittedBarEvent) -> None:
        background_started.set()
        await release_background.wait()

    app = create_http_app(
        ready=True,
        trace_id_factory=lambda: "trace-1",
        process_committed_bar=blocking_use_case,  # type: ignore[arg-type]
    )
    body = json.dumps({"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": 1}).encode()
    request_delivered = False

    async def receive() -> dict[str, object]:
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def send(message: dict[str, object]) -> None:
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            response_sent.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/webhooks/closed-bar",
        "raw_path": b"/v1/webhooks/closed-bar",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(app, scope, receive, send)
        with anyio.fail_after(1):
            await response_sent.wait()
            await background_started.wait()
        assert messages[0]["status"] == 200
        release_background.set()
