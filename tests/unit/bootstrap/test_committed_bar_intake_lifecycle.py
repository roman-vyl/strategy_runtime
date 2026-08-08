"""Lifecycle guardrail tests for the committed-bar intake worker as owned by
the composition root: start-once-at-lifespan-startup, stop-once-at-shutdown,
pending-event discard, in-flight-event completion, event-loop-not-blocked
during the offloaded join, and outbound-client-close ordering."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strategy_runtime.bootstrap.application import build_application
from strategy_runtime.runtime.committed_bar_intake import IntakeNotAccepting
from strategy_runtime.utility.committed_bar import CommittedBarEvent, CommittedBarOrchestrator


def _valid_environ(tmp_path: Path) -> dict[str, str]:
    specs_path = tmp_path / "specs"
    specs_path.mkdir(exist_ok=True)
    return {
        "RUNTIME_SPECS_PATH": str(specs_path),
        "RUNTIME_JOURNAL_PATH": str(tmp_path / "journal" / "runtime.jsonl"),
        "RUNTIME_STRATEGY_ENGINE_BASE_URL": "http://engine.invalid",
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_BASE_URL": "http://abi.invalid",
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS": "5",
        "RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS": "5",
        "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": "256",
    }


def _wait_until(predicate: object, *, timeout: float = 3.0, interval: float = 0.005) -> bool:
    """Bounded, actively-re-checked wait -- see the identical helper and
    rationale in tests/unit/runtime/committed_bar_intake/test_worker.py."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(interval)
    return bool(predicate())  # type: ignore[operator]


class _ProcessGate:
    """Installed over `CommittedBarOrchestrator.process` via monkeypatch: the
    first `gate_count` calls block on a controllable gate; the rest pass
    straight through to the real implementation."""

    def __init__(self, *, gated_calls: int = 1) -> None:
        self.calls: list[CommittedBarEvent] = []
        self.call_started = threading.Event()
        self.release = threading.Event()
        self._gated_calls = gated_calls
        self._lock = threading.Lock()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_process = CommittedBarOrchestrator.process
        gate = self

        def _wrapped(self: CommittedBarOrchestrator, event: CommittedBarEvent) -> object:
            with gate._lock:
                gate.calls.append(event)
                call_index = len(gate.calls)
            if call_index <= gate._gated_calls:
                gate.call_started.set()
                assert gate.release.wait(timeout=5), "gate was never released"
            return real_process(self, event)  # type: ignore[arg-type]

        monkeypatch.setattr(CommittedBarOrchestrator, "process", _wrapped)


def _post(client: TestClient, open_time_ms: int) -> object:
    return client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "5m", "open_time_ms": open_time_ms},
    )


def _start_shutdown_while_first_event_is_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, object, TestClient, _ProcessGate, threading.Event, threading.Thread]:
    """Shared setup for the three tests below: build a ready app, accept one
    webhook whose processing is gated open, start shutdown on a background
    thread (via `client.__exit__`), and wait until the worker has committed
    to STOPPING -- the point at which each test's own assertions diverge.
    """
    gate = _ProcessGate(gated_calls=1)
    gate.install(monkeypatch)

    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker
    client = TestClient(app)
    client.__enter__()

    assert _post(client, 1).status_code == 200
    assert gate.call_started.wait(timeout=2)

    shutdown_done = threading.Event()

    def _shutdown() -> None:
        client.__exit__(None, None, None)
        shutdown_done.set()

    shutdown_thread = threading.Thread(target=_shutdown)
    shutdown_thread.start()
    assert _wait_until(lambda: worker.state == "STOPPING")

    return app, worker, client, gate, shutdown_done, shutdown_thread


# ---------------------------------------------------------------------------
# Worker lifecycle: not started -> running -> stopped
# ---------------------------------------------------------------------------


def test_worker_exists_but_is_not_started_immediately_after_build_application(
    tmp_path: Path,
) -> None:
    app = build_application(_valid_environ(tmp_path))
    assert app.state.ready is True
    worker = app.state.committed_bar_intake_worker
    assert worker is not None
    assert worker.state == "NOT_STARTED"
    assert worker._thread is None


def test_worker_is_running_exactly_once_after_lifespan_startup(tmp_path: Path) -> None:
    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker

    with TestClient(app):
        assert worker.state == "RUNNING"
        assert worker._thread is not None
        assert worker._thread.is_alive()


def test_worker_is_stopped_and_thread_not_alive_after_lifespan_shutdown(tmp_path: Path) -> None:
    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker

    with TestClient(app):
        assert worker.state == "RUNNING"

    assert worker.state == "STOPPED"
    assert worker._thread is not None
    assert not worker._thread.is_alive()


# ---------------------------------------------------------------------------
# Shutdown semantics: pending discard, in-flight completion, client-close
# ordering, stop-accepting-first.
# ---------------------------------------------------------------------------


def test_shutdown_discards_pending_events_but_lets_the_current_one_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _ProcessGate(gated_calls=1)
    gate.install(monkeypatch)

    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker

    with TestClient(app) as client:
        assert _post(client, 1).status_code == 200
        assert _post(client, 2).status_code == 200
        assert _post(client, 3).status_code == 200
        assert gate.call_started.wait(timeout=2), "worker never started processing the first event"

        def _release_once_stopping() -> None:
            assert _wait_until(lambda: worker.state == "STOPPING")
            gate.release.set()

        releaser = threading.Thread(target=_release_once_stopping)
        releaser.start()
        # Exiting the `with` block below triggers shutdown; it blocks until
        # stop_once() fully returns, by which point the releaser above has
        # already unblocked the gated first event.
    releaser.join(timeout=5)

    assert len(gate.calls) == 1
    assert gate.calls[0].open_time_ms == 1
    assert worker.state == "STOPPED"


def test_shutdown_waits_for_the_in_flight_event_to_finish_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, worker, _client, gate, shutdown_done, shutdown_thread = (
        _start_shutdown_while_first_event_is_gated(tmp_path, monkeypatch)
    )
    try:
        # stop_once() must not have returned while the gate is still held.
        assert not shutdown_done.wait(timeout=0.2)
        gate.release.set()
        shutdown_thread.join(timeout=5)
        assert shutdown_done.is_set()
    finally:
        gate.release.set()
        shutdown_thread.join(timeout=5)

    assert worker.state == "STOPPED"
    assert len(gate.calls) == 1


def test_outbound_clients_close_only_after_the_worker_has_fully_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _worker, _client, gate, shutdown_done, shutdown_thread = (
        _start_shutdown_while_first_event_is_gated(tmp_path, monkeypatch)
    )
    try:
        # The worker thread may still be mid-process(...); clients must stay open.
        assert not shutdown_done.wait(timeout=0.2)
        assert all(not c._client.is_closed for c in app.state.outbound_http_clients)  # type: ignore[attr-defined]

        gate.release.set()
        shutdown_thread.join(timeout=5)
    finally:
        gate.release.set()
        shutdown_thread.join(timeout=5)

    assert all(c._client.is_closed for c in app.state.outbound_http_clients)  # type: ignore[attr-defined]


def test_stop_accepting_takes_effect_immediately_regardless_of_in_flight_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, _worker, client, gate, _shutdown_done, shutdown_thread = (
        _start_shutdown_while_first_event_is_gated(tmp_path, monkeypatch)
    )
    try:
        rejected = _post(client, 2)
        assert rejected.status_code == 503  # type: ignore[union-attr]
        assert rejected.json() == {"status": "not_ready"}  # type: ignore[union-attr]
        assert len(gate.calls) == 1  # the rejected request never reached the worker
    finally:
        gate.release.set()
        shutdown_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Event loop is not blocked while the offloaded stop_once() join is pending.
# ---------------------------------------------------------------------------


async def _await_until(predicate: object, *, timeout: float = 3.0, interval: float = 0.005) -> bool:
    import anyio

    deadline = anyio.current_time() + timeout
    while anyio.current_time() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        await anyio.sleep(interval)
    return bool(predicate())  # type: ignore[operator]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_event_loop_keeps_running_while_the_offloaded_join_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import anyio

    gate = _ProcessGate(gated_calls=1)
    gate.install(monkeypatch)

    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker
    intake = app.state.committed_bar_intake

    context = app.router.lifespan_context(app)
    await context.__aenter__()
    assert worker.state == "RUNNING"

    intake.put_nowait(CommittedBarEvent("BTCUSDT.P", "5m", 1))
    assert await _await_until(lambda: gate.call_started.is_set())

    probe_ticks = {"n": 0}
    stop_probe = anyio.Event()

    async def _probe() -> None:
        while not stop_probe.is_set():
            probe_ticks["n"] += 1
            await anyio.sleep(0)

    shutdown_done = anyio.Event()

    async def _exit_context() -> None:
        await context.__aexit__(None, None, None)
        shutdown_done.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_probe)
        task_group.start_soon(_exit_context)

        assert await _await_until(lambda: worker.state == "STOPPING")
        ticks_while_gated_before = probe_ticks["n"]
        for _ in range(25):
            await anyio.sleep(0)
        assert probe_ticks["n"] > ticks_while_gated_before, (
            "event loop appears blocked while the offloaded worker-stop join is pending"
        )
        assert not shutdown_done.is_set()
        assert all(not c._client.is_closed for c in app.state.outbound_http_clients)  # type: ignore[attr-defined]

        gate.release.set()
        assert await _await_until(lambda: shutdown_done.is_set())
        stop_probe.set()

    assert worker.state == "STOPPED"
    assert all(c._client.is_closed for c in app.state.outbound_http_clients)  # type: ignore[attr-defined]
    assert not worker._thread.is_alive()  # type: ignore[union-attr]


def test_no_orphan_worker_thread_remains_after_clean_shutdown(tmp_path: Path) -> None:
    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker

    with TestClient(app):
        pass

    live_threads = [t for t in threading.enumerate() if t is worker._thread]
    assert live_threads == []
    assert worker._thread is not None
    assert not worker._thread.is_alive()


# ---------------------------------------------------------------------------
# Startup-rollback: a later construction failure leaves no running worker.
# ---------------------------------------------------------------------------


def test_construction_failure_leaves_ready_false_with_no_running_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import strategy_runtime.bootstrap.application as application_module

    def _raise_on_construction(**_kwargs: object) -> object:
        raise ValueError("simulated invalid ABI entry-package configuration")

    monkeypatch.setattr(application_module, "HttpxAbiEntryPackageAdapter", _raise_on_construction)

    app = build_application(_valid_environ(tmp_path))

    assert app.state.ready is False
    assert app.state.committed_bar_intake is None
    threads_named_intake_worker = [
        t for t in threading.enumerate() if t.name == "committed-bar-intake-worker"
    ]
    assert threads_named_intake_worker == []


# ---------------------------------------------------------------------------
# Lifespan-startup failure: intake_worker.start() raising must not skip
# cleanup or be swallowed to fake a ready application.
# ---------------------------------------------------------------------------


def test_lifespan_startup_failure_still_runs_full_cleanup_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    app = build_application(_valid_environ(tmp_path))
    worker = app.state.committed_bar_intake_worker
    intake = app.state.committed_bar_intake

    real_thread_start = threading.Thread.start

    def _raising_thread_start(self: threading.Thread) -> None:
        if self.name == "committed-bar-intake-worker":
            raise RuntimeError("simulated OS thread creation failure")
        real_thread_start(self)

    monkeypatch.setattr(threading.Thread, "start", _raising_thread_start)

    async def _enter_and_exit_lifespan() -> None:
        async with app.router.lifespan_context(app):
            raise AssertionError("lifespan must fail before ever yielding")

    with pytest.raises(RuntimeError, match="simulated OS thread creation failure"):
        asyncio.run(_enter_and_exit_lifespan())

    # The startup error was not swallowed to pretend readiness: it propagated
    # out of the lifespan context manager (asserted above). Cleanup still ran
    # in full despite that failure:
    assert worker.state == "STOPPED"

    with pytest.raises(IntakeNotAccepting):
        intake.put_nowait(CommittedBarEvent("BTCUSDT.P", "5m", 1))

    assert all(
        client._client.is_closed  # type: ignore[attr-defined]
        for client in app.state.outbound_http_clients
    )

    assert not any(thread.name == "committed-bar-intake-worker" for thread in threading.enumerate())

    # stop_once() afterward remains a safe no-op against the start-failure
    # terminal state.
    worker.stop_once()
    assert worker.state == "STOPPED"
