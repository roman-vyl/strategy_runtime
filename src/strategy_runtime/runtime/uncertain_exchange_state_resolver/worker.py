"""Background polling worker driving `UncertainExchangeStateResolver`.

Modeled on `CommittedBarIntakeWorker`'s lifecycle shape, but ticks on a fixed
polling interval instead of draining a queue: resolution runs independently
of committed-bar cadence, so this worker has no upstream event source to
block on.
"""

import logging
import threading
from enum import Enum, auto

from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.runtime.uncertain_exchange_state_resolver.resolver import (
    UncertainExchangeStateResolver,
)

_DEFAULT_POLL_INTERVAL_SECONDS = 30.0


class _State(Enum):
    NOT_STARTED = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


class UncertainExchangeStateResolverWorker:
    """Own the single dedicated thread that polls for pending-recovery markers."""

    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        resolver: UncertainExchangeStateResolver,
        logger: logging.Logger,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        if type(poll_interval_seconds) not in {int, float} or poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be a positive number")
        self._state_repository = state_repository
        self._resolver = resolver
        self._poll_interval_seconds = poll_interval_seconds
        self._logger = logger
        self._lifecycle_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._state = _State.NOT_STARTED
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()

    @property
    def state(self) -> str:
        return self._state.name

    def start(self) -> None:
        thread = threading.Thread(
            target=self._run,
            name="uncertain-exchange-state-resolver-worker",
            daemon=False,
        )
        with self._lifecycle_lock:
            if self._state is not _State.NOT_STARTED:
                raise RuntimeError(
                    "UncertainExchangeStateResolverWorker.start() called more than once"
                )
            self._thread = thread
            self._state = _State.RUNNING
            try:
                thread.start()
            except BaseException:
                # thread.start() raised before the OS thread ever began
                # running _run(): no thread exists to join (see the matching
                # comment in CommittedBarIntakeWorker.start()).
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
            self._wake.set()
            assert thread is not None
            thread.join()
            with self._lifecycle_lock:
                self._state = _State.STOPPED

    def _run(self) -> None:
        while True:
            with self._lifecycle_lock:
                if self._state is not _State.RUNNING:
                    return
            self._tick()
            if self._wake.wait(timeout=self._poll_interval_seconds):
                self._wake.clear()

    def _tick(self) -> None:
        pending_ids = (
            *self._state_repository.list_ids_with_pending_entry_recovery(),
            *self._state_repository.list_ids_with_pending_close_recovery(),
        )
        for strategy_instance_id in pending_ids:
            with self._lifecycle_lock:
                if self._state is not _State.RUNNING:
                    return
            try:
                self._resolver.attempt(strategy_instance_id)
            except Exception:
                self._logger.exception(
                    "uncertain-exchange-state-resolver worker failed to resolve one instance"
                )
