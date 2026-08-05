import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from strategy_runtime.runtime.committed_bar_intake import CommittedBarIntakeBoundary
from strategy_runtime.runtime.committed_bar_intake.worker import CommittedBarIntakeWorker
from strategy_runtime.utility.committed_bar import CommittedBarEvent

_LOGGER = logging.getLogger("test.committed_bar_intake.worker")


def _event(open_time_ms: int = 1) -> CommittedBarEvent:
    return CommittedBarEvent("BTCUSDT.P", "5m", open_time_ms)


def _wait_until(predicate: object, *, timeout: float = 2.0, interval: float = 0.005) -> bool:
    """Bounded, actively-re-checked wait for a predicate to become true.

    Not a proof-by-sleep: the loop only returns True once the predicate is
    observed true, and returns False (causing the caller's assertion to
    fail) if it never becomes true within `timeout` -- used only for the one
    case here (a lock-guarded state transition) that has no dedicated
    `threading.Event` of its own to wait on.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(interval)
    return bool(predicate())  # type: ignore[operator]


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls: list[CommittedBarEvent] = []
        self._lock = threading.Lock()

    def process(self, event: CommittedBarEvent) -> None:
        with self._lock:
            self.calls.append(event)


class RaisingThenRecordingOrchestrator:
    def __init__(self) -> None:
        self.calls: list[CommittedBarEvent] = []

    def process(self, event: CommittedBarEvent) -> None:
        self.calls.append(event)
        if len(self.calls) == 1:
            raise RuntimeError("simulated CommittedBarPreparationError")


class GatedOrchestrator:
    """A fake orchestrator whose `process` blocks on a controllable gate.

    `call_started` fires the instant `process(...)` begins; the call does
    not return until `release_gate` is set from the test thread.
    """

    def __init__(self) -> None:
        self.calls: list[CommittedBarEvent] = []
        self.call_started = threading.Event()
        self.release_gate = threading.Event()
        self._concurrent_calls = 0
        self._peak_concurrent_calls = 0
        self._lock = threading.Lock()

    def process(self, event: CommittedBarEvent) -> None:
        with self._lock:
            self.calls.append(event)
            self._concurrent_calls += 1
            self._peak_concurrent_calls = max(self._peak_concurrent_calls, self._concurrent_calls)
        self.call_started.set()
        assert self.release_gate.wait(timeout=5), "process() gate was never released"
        with self._lock:
            self._concurrent_calls -= 1


def test_start_transitions_not_started_to_running_and_spawns_exactly_one_thread() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RecordingOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]

    assert worker.state == "NOT_STARTED"
    assert worker._thread is None

    worker.start()
    try:
        assert worker.state == "RUNNING"
        assert worker._thread is not None
        assert worker._thread.is_alive()
        assert worker._thread.daemon is False
    finally:
        worker.stop_once()

    assert worker.state == "STOPPED"
    assert not worker._thread.is_alive()


def test_start_called_twice_raises_instead_of_silently_no_opping() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RecordingOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]

    worker.start()
    try:
        with pytest.raises(RuntimeError):
            worker.start()
    finally:
        worker.stop_once()


def test_stop_once_before_start_transitions_directly_to_stopped_without_joining() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RecordingOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]

    assert worker.state == "NOT_STARTED"
    worker.stop_once()
    assert worker.state == "STOPPED"
    assert worker._thread is None


def test_stop_once_after_already_stopped_is_a_no_op() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RecordingOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]
    worker.start()
    worker.stop_once()
    assert worker.state == "STOPPED"

    worker.stop_once()  # no exception, no-op
    assert worker.state == "STOPPED"


def test_fifo_processing_order_across_three_events() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RecordingOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]

    intake.put_nowait(_event(1))
    intake.put_nowait(_event(2))
    intake.put_nowait(_event(3))

    worker.start()
    try:
        assert _wait_until(lambda: len(orchestrator.calls) == 3)
    finally:
        worker.stop_once()

    assert orchestrator.calls == [_event(1), _event(2), _event(3)]


def test_one_event_processing_exception_does_not_kill_the_worker() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RaisingThenRecordingOrchestrator()
    fake_logger = logging.getLogger("test.committed_bar_intake.worker.raising")
    logged: list[str] = []
    fake_logger.exception = lambda msg, *a, **k: logged.append(msg)  # type: ignore[method-assign]
    worker = CommittedBarIntakeWorker(intake, orchestrator, fake_logger)  # type: ignore[arg-type]

    intake.put_nowait(_event(1))
    intake.put_nowait(_event(2))

    worker.start()
    try:
        assert _wait_until(lambda: len(orchestrator.calls) == 2)
        assert _wait_until(lambda: worker._thread is not None and worker._thread.is_alive())
    finally:
        worker.stop_once()

    assert orchestrator.calls == [_event(1), _event(2)]
    assert len(logged) == 1


def test_at_most_one_process_call_in_flight_at_any_instant() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = GatedOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]

    intake.put_nowait(_event(1))
    intake.put_nowait(_event(2))

    worker.start()
    try:
        assert orchestrator.call_started.wait(timeout=2)
        # The second event must not have started while the first is gated.
        time_waited_for_second = orchestrator.call_started.is_set()
        assert time_waited_for_second
        assert len(orchestrator.calls) == 1

        orchestrator.call_started.clear()
        orchestrator.release_gate.set()

        assert orchestrator.call_started.wait(timeout=2)
        assert _wait_until(lambda: len(orchestrator.calls) == 2)
        orchestrator.release_gate.set()
    finally:
        orchestrator.release_gate.set()
        worker.stop_once()

    assert orchestrator._peak_concurrent_calls == 1
    assert orchestrator.calls == [_event(1), _event(2)]


def test_lifecycle_lock_is_not_held_while_process_is_executing() -> None:
    """If `_lifecycle_lock` were (incorrectly) held across `process(...)`,
    a concurrent `stop_once()` call would deadlock waiting for it and never
    reach `STOPPING` while the gate is held -- so observing the `STOPPING`
    transition within a bounded wait, while `process()` is still blocked,
    proves the lock was free."""
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = GatedOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]
    intake.put_nowait(_event(1))
    worker.start()

    assert orchestrator.call_started.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stop_future = executor.submit(worker.stop_once)
        assert _wait_until(lambda: worker.state == "STOPPING")
        # process() is still blocked on the gate -- stop_once() has not
        # returned, proving it reached STOPPING without process() finishing.
        assert not stop_future.done()
        orchestrator.release_gate.set()
        stop_future.result(timeout=3)

    assert worker.state == "STOPPED"
    assert orchestrator.calls == [_event(1)]


def test_dequeue_vs_stop_race_event_already_current_is_allowed_to_finish() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = GatedOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]
    intake.put_nowait(_event(1))
    worker.start()

    # The event has already become "current" (process() has started, which
    # only happens after _run() released _lifecycle_lock following a
    # RUNNING decision) before stop_once() is invoked.
    assert orchestrator.call_started.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stop_future = executor.submit(worker.stop_once)
        assert _wait_until(lambda: worker.state == "STOPPING")
        assert not stop_future.done(), "stop_once() must wait for the current event to finish"
        orchestrator.release_gate.set()
        stop_future.result(timeout=3)

    assert orchestrator.calls == [_event(1)]
    assert worker.state == "STOPPED"


def test_dequeue_vs_stop_race_stop_wins_discards_the_event() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = RecordingOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]

    dequeued = threading.Event()
    release_dequeue = threading.Event()
    real_get = intake.get

    def _gated_get(timeout: float) -> CommittedBarEvent:
        event = real_get(timeout=timeout)
        dequeued.set()
        assert release_dequeue.wait(timeout=5)
        return event

    intake.get = _gated_get  # type: ignore[method-assign]

    intake.put_nowait(_event(1))
    worker.start()

    assert dequeued.wait(timeout=2), "worker never dequeued the event"

    with ThreadPoolExecutor(max_workers=1) as executor:
        stop_future = executor.submit(worker.stop_once)
        # stop_once() must win the lifecycle-lock race and commit STOPPING
        # while _run() is still parked inside the gated get(), i.e. before
        # the dequeued event ever reaches its own lock acquisition.
        assert _wait_until(lambda: worker.state == "STOPPING")
        release_dequeue.set()
        stop_future.result(timeout=3)

    assert orchestrator.calls == []
    assert worker.state == "STOPPED"
    assert not worker._thread.is_alive()  # type: ignore[union-attr]


def test_concurrent_stop_once_callers_only_one_performs_the_join() -> None:
    intake = CommittedBarIntakeBoundary(capacity=8)
    orchestrator = GatedOrchestrator()
    worker = CommittedBarIntakeWorker(intake, orchestrator, _LOGGER)  # type: ignore[arg-type]
    intake.put_nowait(_event(1))
    worker.start()
    assert orchestrator.call_started.wait(timeout=2)

    join_calls = 0
    join_calls_lock = threading.Lock()
    real_join = worker._thread.join  # type: ignore[union-attr]

    def _counting_join(*args: object, **kwargs: object) -> None:
        nonlocal join_calls
        with join_calls_lock:
            join_calls += 1
        real_join(*args, **kwargs)

    worker._thread.join = _counting_join  # type: ignore[union-attr, method-assign]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker.stop_once)
        second = executor.submit(worker.stop_once)
        assert _wait_until(lambda: worker.state == "STOPPING")
        orchestrator.release_gate.set()
        first.result(timeout=3)
        second.result(timeout=3)

    assert join_calls == 1
    assert worker.state == "STOPPED"
