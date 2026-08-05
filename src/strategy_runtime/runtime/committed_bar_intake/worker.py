"""Exactly-one consumer worker for the committed-bar intake boundary."""

import logging
import queue
import threading
from enum import Enum, auto
from typing import Any

from strategy_runtime.runtime.committed_bar_intake.boundary import CommittedBarIntakeBoundary
from strategy_runtime.utility.committed_bar import CommittedBarEvent, CommittedBarOrchestrator

_GET_POLL_SECONDS = 0.2


class _State(Enum):
    NOT_STARTED = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


class CommittedBarIntakeWorker:
    """Own the single dedicated thread that drains the intake boundary.

    At most one `CommittedBarOrchestrator.process` call is ever in flight:
    there is exactly one consumer thread, and the atomic stop/start state
    machine below guarantees at most one event is ever "current" at a time.
    """

    def __init__(
        self,
        intake: CommittedBarIntakeBoundary,
        orchestrator: CommittedBarOrchestrator[Any, Any],
        logger: logging.Logger,
    ) -> None:
        self._intake = intake
        self._orchestrator = orchestrator
        self._logger = logger
        self._lifecycle_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._state = _State.NOT_STARTED
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> str:
        return self._state.name

    def start(self) -> None:
        thread = threading.Thread(
            target=self._run,
            name="committed-bar-intake-worker",
            daemon=False,
        )
        with self._lifecycle_lock:
            if self._state is not _State.NOT_STARTED:
                raise RuntimeError("CommittedBarIntakeWorker.start() called more than once")
            self._thread = thread
            self._state = _State.RUNNING
            try:
                thread.start()
            except BaseException:
                # thread.start() raised before the OS thread ever began
                # running _run(): no thread exists to join, so the worker
                # goes directly to one explicit terminal state instead of
                # being left RUNNING (a lie) or STOPPING (implies a join is
                # still owed). stop_once() afterward is then a plain no-op.
                self._state = _State.STOPPED
                raise

    def stop_once(self) -> None:
        with self._stop_lock:
            with self._lifecycle_lock:
                if self._state is _State.NOT_STARTED:
                    self._state = _State.STOPPED
                    return
                if self._state is _State.STOPPED:
                    return
                self._state = _State.STOPPING
                thread = self._thread
            assert thread is not None
            thread.join()
            with self._lifecycle_lock:
                self._state = _State.STOPPED

    def _run(self) -> None:
        while True:
            try:
                event = self._intake.get(timeout=_GET_POLL_SECONDS)
            except queue.Empty:
                with self._lifecycle_lock:
                    if self._state is not _State.RUNNING:
                        return
                continue

            with self._lifecycle_lock:
                if self._state is not _State.RUNNING:
                    self._intake.task_done()
                    return
                current = event

            self._process_current(current)

    def _process_current(self, current: CommittedBarEvent) -> None:
        try:
            self._orchestrator.process(current)
        except Exception:
            self._logger.exception("committed-bar intake worker failed to process one event")
        finally:
            self._intake.task_done()
