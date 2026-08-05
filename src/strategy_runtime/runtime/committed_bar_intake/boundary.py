"""Bounded process-local FIFO intake boundary for committed-bar events."""

import queue
import threading

from strategy_runtime.utility.committed_bar import CommittedBarEvent


class IntakeNotAccepting(Exception):
    """Raised by `put_nowait` once `stop_accepting()` has already run."""


class CommittedBarIntakeBoundary:
    """The sole owner of the bounded `queue.Queue[CommittedBarEvent]`.

    No caller outside this class holds a reference to the underlying
    `queue.Queue` directly. `put_nowait` and `stop_accepting` share one lock
    so the two operations linearize: either a given `put_nowait` call
    acquires the lock before a concurrent `stop_accepting()` call (the event
    reaches the underlying queue, subject to the normal capacity check), or
    `stop_accepting` acquires it first (`put_nowait` raises
    `IntakeNotAccepting` before ever calling the underlying queue's
    `put_nowait`).
    """

    def __init__(self, capacity: int) -> None:
        if type(capacity) is not int or capacity <= 0:
            # queue.Queue(maxsize=0) or a negative maxsize silently means
            # "unbounded" -- reject here so this boundary can never become
            # an accidental unbounded queue. `bool` is explicitly rejected
            # too (`type(True) is not int`), since `True`/`False` are not
            # meaningful queue capacities even though `bool` subclasses
            # `int`.
            raise ValueError("CommittedBarIntakeBoundary capacity must be a positive int")
        self._queue: queue.Queue[CommittedBarEvent] = queue.Queue(maxsize=capacity)
        self._accept_lock = threading.Lock()
        self._accepting = True

    @property
    def capacity(self) -> int:
        return self._queue.maxsize

    def put_nowait(self, event: CommittedBarEvent) -> None:
        with self._accept_lock:
            if not self._accepting:
                raise IntakeNotAccepting
            self._queue.put_nowait(event)

    def stop_accepting(self) -> None:
        with self._accept_lock:
            self._accepting = False

    def get(self, timeout: float) -> CommittedBarEvent:
        """Worker-only: dequeue the next event, blocking up to `timeout`."""
        return self._queue.get(timeout=timeout)

    def task_done(self) -> None:
        """Worker-only: mark the most recently dequeued event as handled."""
        self._queue.task_done()
