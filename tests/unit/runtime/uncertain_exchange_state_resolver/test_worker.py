"""`UncertainExchangeStateResolverWorker`: fixed-interval polling lifecycle,
modeled on `CommittedBarIntakeWorker` (see task 6.2-6.4)."""

import logging
import threading
import time

import pytest

from strategy_runtime.runtime.uncertain_exchange_state_resolver.worker import (
    UncertainExchangeStateResolverWorker,
)

_LOGGER = logging.getLogger("test.uncertain_exchange_state_resolver.worker")
_FAST_INTERVAL_SECONDS = 0.01


def _wait_until(predicate: object, *, timeout: float = 2.0, interval: float = 0.005) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(interval)
    return bool(predicate())  # type: ignore[operator]


class RecordingRepository:
    def __init__(self, pending_ids: tuple[str, ...] = ()) -> None:
        self.pending_ids = pending_ids

    def list_ids_with_pending_entry_recovery(self) -> tuple[str, ...]:
        return self.pending_ids

    def list_ids_with_pending_close_recovery(self) -> tuple[str, ...]:
        return ()


class RecordingResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def attempt(self, strategy_instance_id: str) -> None:
        with self._lock:
            self.calls.append(strategy_instance_id)


class RaisingThenRecordingResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def attempt(self, strategy_instance_id: str) -> None:
        self.calls.append(strategy_instance_id)
        if strategy_instance_id == "boom":
            raise RuntimeError("simulated resolution failure")


class GatedResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.call_started = threading.Event()
        self.release_gate = threading.Event()

    def attempt(self, strategy_instance_id: str) -> None:
        self.calls.append(strategy_instance_id)
        self.call_started.set()
        assert self.release_gate.wait(timeout=5), "attempt() gate was never released"


def test_start_transitions_not_started_to_running_and_spawns_exactly_one_thread() -> None:
    repository = RecordingRepository()
    resolver = RecordingResolver()
    worker = UncertainExchangeStateResolverWorker(
        state_repository=repository,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

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
    worker = UncertainExchangeStateResolverWorker(
        state_repository=RecordingRepository(),  # type: ignore[arg-type]
        resolver=RecordingResolver(),  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

    worker.start()
    try:
        with pytest.raises(RuntimeError):
            worker.start()
    finally:
        worker.stop_once()


def test_stop_once_before_start_transitions_directly_to_stopped_without_joining() -> None:
    worker = UncertainExchangeStateResolverWorker(
        state_repository=RecordingRepository(),  # type: ignore[arg-type]
        resolver=RecordingResolver(),  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

    assert worker.state == "NOT_STARTED"
    worker.stop_once()
    assert worker.state == "STOPPED"
    assert worker._thread is None


def test_stop_once_after_already_stopped_is_a_no_op() -> None:
    worker = UncertainExchangeStateResolverWorker(
        state_repository=RecordingRepository(),  # type: ignore[arg-type]
        resolver=RecordingResolver(),  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )
    worker.start()
    worker.stop_once()
    assert worker.state == "STOPPED"

    worker.stop_once()
    assert worker.state == "STOPPED"


def test_rejects_non_positive_poll_interval() -> None:
    with pytest.raises(ValueError):
        UncertainExchangeStateResolverWorker(
            state_repository=RecordingRepository(),  # type: ignore[arg-type]
            resolver=RecordingResolver(),  # type: ignore[arg-type]
            logger=_LOGGER,
            poll_interval_seconds=0,
        )


def test_one_tick_attempts_every_currently_pending_instance() -> None:
    repository = RecordingRepository(("a", "b", "c"))
    resolver = RecordingResolver()
    worker = UncertainExchangeStateResolverWorker(
        state_repository=repository,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

    worker.start()
    try:
        assert _wait_until(lambda: set(resolver.calls) >= {"a", "b", "c"})
    finally:
        worker.stop_once()

    assert {"a", "b", "c"}.issubset(set(resolver.calls))


def test_no_pending_instances_means_no_attempts() -> None:
    repository = RecordingRepository(())
    resolver = RecordingResolver()
    worker = UncertainExchangeStateResolverWorker(
        state_repository=repository,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

    worker.start()
    try:
        time.sleep(_FAST_INTERVAL_SECONDS * 5)
    finally:
        worker.stop_once()

    assert resolver.calls == []


def test_one_instance_resolution_failure_does_not_prevent_attempting_the_others() -> None:
    repository = RecordingRepository(("boom", "other"))
    resolver = RaisingThenRecordingResolver()
    fake_logger = logging.getLogger("test.uncertain_exchange_state_resolver.worker.raising")
    logged: list[str] = []
    fake_logger.exception = lambda msg, *a, **k: logged.append(msg)  # type: ignore[method-assign]
    worker = UncertainExchangeStateResolverWorker(
        state_repository=repository,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        logger=fake_logger,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

    worker.start()
    try:
        assert _wait_until(lambda: "other" in resolver.calls)
        assert _wait_until(lambda: worker._thread is not None and worker._thread.is_alive())
    finally:
        worker.stop_once()

    assert "boom" in resolver.calls
    assert "other" in resolver.calls
    assert len(logged) >= 1


def test_graceful_shutdown_joins_an_in_flight_attempt_before_returning() -> None:
    repository = RecordingRepository(("a",))
    resolver = GatedResolver()
    worker = UncertainExchangeStateResolverWorker(
        state_repository=repository,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        logger=_LOGGER,
        poll_interval_seconds=_FAST_INTERVAL_SECONDS,
    )

    worker.start()
    assert resolver.call_started.wait(timeout=2)

    stop_done = threading.Event()

    def _stop() -> None:
        worker.stop_once()
        stop_done.set()

    stop_thread = threading.Thread(target=_stop)
    stop_thread.start()

    assert not stop_done.wait(timeout=0.2), "stop_once() must wait for the in-flight attempt"
    resolver.release_gate.set()
    stop_thread.join(timeout=5)

    assert stop_done.is_set()
    assert worker.state == "STOPPED"
    assert not worker._thread.is_alive()  # type: ignore[union-attr]
