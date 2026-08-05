import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from strategy_runtime.runtime.committed_bar_intake import (
    CommittedBarIntakeBoundary,
    IntakeNotAccepting,
)
from strategy_runtime.utility.committed_bar import CommittedBarEvent


def _event(open_time_ms: int = 1) -> CommittedBarEvent:
    return CommittedBarEvent("BTCUSDT.P", "5m", open_time_ms)


def test_put_nowait_then_get_returns_the_same_event_fifo() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=8)
    boundary.put_nowait(_event(1))
    boundary.put_nowait(_event(2))
    boundary.put_nowait(_event(3))

    assert boundary.get(timeout=1) == _event(1)
    assert boundary.get(timeout=1) == _event(2)
    assert boundary.get(timeout=1) == _event(3)
    with pytest.raises(queue.Empty):
        boundary.get(timeout=0)


def test_capacity_is_reflected_exactly_as_the_underlying_queue_maxsize() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=17)
    assert boundary.capacity == 17


def test_put_nowait_raises_queue_full_at_capacity_without_evicting_existing_items() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=1)
    boundary.put_nowait(_event(1))

    with pytest.raises(queue.Full):
        boundary.put_nowait(_event(2))

    # The existing item is untouched, in its original position.
    assert boundary.get(timeout=0) == _event(1)
    with pytest.raises(queue.Empty):
        boundary.get(timeout=0)


def test_stop_accepting_then_put_nowait_raises_intake_not_accepting() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=8)
    boundary.stop_accepting()

    with pytest.raises(IntakeNotAccepting):
        boundary.put_nowait(_event())

    with pytest.raises(queue.Empty):
        boundary.get(timeout=0)


def test_stop_accepting_does_not_disturb_events_already_enqueued() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=8)
    boundary.put_nowait(_event(1))
    boundary.stop_accepting()

    assert boundary.get(timeout=0) == _event(1)


def test_intake_not_accepting_is_a_distinct_exception_from_queue_full() -> None:
    assert not issubclass(IntakeNotAccepting, queue.Full)
    assert not issubclass(queue.Full, IntakeNotAccepting)


def test_task_done_delegates_to_the_underlying_queue_join_accounting() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=8)
    boundary.put_nowait(_event())
    boundary.get(timeout=1)

    joined = threading.Event()

    def _join() -> None:
        boundary._queue.join()  # test-only introspection of join() accounting
        joined.set()

    joiner = threading.Thread(target=_join)
    joiner.start()
    assert not joined.wait(timeout=0.2)

    boundary.task_done()
    joiner.join(timeout=2)
    assert joined.is_set()


def test_linearization_put_nowait_before_stop_accepting_is_accepted() -> None:
    """A put_nowait call that already acquired the shared lock before a
    concurrent stop_accepting() call started must succeed -- proven here by
    holding the lock ourselves to simulate "put_nowait won the race", then
    confirming stop_accepting() only takes effect for the next call."""
    boundary = CommittedBarIntakeBoundary(capacity=8)
    put_running = threading.Event()
    release_put = threading.Event()
    real_put_nowait = queue.Queue.put_nowait

    def _slow_put_nowait(self: queue.Queue, item: object) -> None:
        put_running.set()
        assert release_put.wait(timeout=2)
        real_put_nowait(self, item)

    boundary._queue.put_nowait = lambda item: _slow_put_nowait(boundary._queue, item)  # type: ignore[method-assign]

    result: dict[str, object] = {}

    def _put() -> None:
        boundary.put_nowait(_event(1))

    def _stop() -> None:
        assert put_running.wait(timeout=2)
        boundary.stop_accepting()
        result["stopped"] = True

    with ThreadPoolExecutor(max_workers=2) as executor:
        put_future = executor.submit(_put)
        stop_future = executor.submit(_stop)
        assert put_running.wait(timeout=2)
        # stop_accepting() must block behind the held _accept_lock until the
        # in-progress put_nowait releases it.
        assert "stopped" not in result
        release_put.set()
        put_future.result(timeout=3)
        stop_future.result(timeout=3)

    assert boundary.get(timeout=0) == _event(1)
    with pytest.raises(IntakeNotAccepting):
        boundary.put_nowait(_event(2))


def test_linearization_stop_accepting_before_put_nowait_is_rejected() -> None:
    boundary = CommittedBarIntakeBoundary(capacity=8)
    boundary.stop_accepting()

    with pytest.raises(IntakeNotAccepting):
        boundary.put_nowait(_event())

    with pytest.raises(queue.Empty):
        boundary.get(timeout=0)
