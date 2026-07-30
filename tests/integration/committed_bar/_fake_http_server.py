"""Real-socket fake HTTP server for I4d production-composition E2E tests.

`build_application` constructs real `httpx.Client` instances against
`RUNTIME_STRATEGY_ENGINE_BASE_URL`/`RUNTIME_ABI_BASE_URL` with no transport
override -- there is no test-injection seam in the composition root by
design (see design.md "Rejected alternatives"). Exercising the full
production composition therefore requires a real listening HTTP server, not
an `httpx.MockTransport` fake.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Handler = Callable[["RecordedRequest"], "FakeResponse"]


class RecordedRequest:
    def __init__(self, method: str, path: str, body: bytes) -> None:
        self.method = method
        self.path = path
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class FakeResponse:
    def __init__(self, status_code: int, body: Any = None, *, delay_seconds: float = 0.0) -> None:
        self.status_code = status_code
        self.body = body
        self.delay_seconds = delay_seconds


class FakeHttpServer:
    """One real `127.0.0.1` HTTP server dispatching every request to `handler`."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.requests: list[RecordedRequest] = []
        self._lock = threading.Lock()
        outer = self

        class _RequestHandler(BaseHTTPRequestHandler):
            def _dispatch(self) -> None:
                length = int(self.headers.get("content-length", 0) or 0)
                body = self.rfile.read(length) if length else b""
                recorded = RecordedRequest(self.command, self.path, body)
                with outer._lock:
                    outer.requests.append(recorded)
                response = outer._handler(recorded)
                if response.delay_seconds:
                    time.sleep(response.delay_seconds)
                payload = (
                    b"" if response.body is None else json.dumps(response.body).encode("utf-8")
                )
                self.send_response(response.status_code)
                if payload:
                    self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802
                self._dispatch()

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch()

            def do_PUT(self) -> None:  # noqa: N802
                self._dispatch()

            def log_message(self, log_format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _RequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> FakeHttpServer:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def sequential(*responders: Handler | FakeResponse) -> Handler:
    """Dispatch to `responders` in order by call count, repeating the last one."""
    calls: list[int] = [0]
    lock = threading.Lock()

    def handle(request: RecordedRequest) -> FakeResponse:
        with lock:
            index = min(calls[0], len(responders) - 1)
            calls[0] += 1
        target = responders[index]
        if isinstance(target, FakeResponse):
            return target
        return target(request)

    return handle


def route(routes: dict[str, Handler | FakeResponse], *, not_found: FakeResponse) -> Handler:
    """Dispatch by exact request path to a per-path handler or canned response."""

    def handle(request: RecordedRequest) -> FakeResponse:
        target = routes.get(request.path)
        if target is None:
            return not_found
        if isinstance(target, FakeResponse):
            return target
        return target(request)

    return handle


def path_prefix_route(
    routes: dict[str, Handler | FakeResponse], *, not_found: FakeResponse
) -> Handler:
    """Dispatch by request-path substring containment, first match wins."""

    def handle(request: RecordedRequest) -> FakeResponse:
        for key, target in routes.items():
            if key in request.path:
                if isinstance(target, FakeResponse):
                    return target
                return target(request)
        return not_found

    return handle
