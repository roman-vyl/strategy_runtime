"""Process-local keyed mutual exclusion for strategy-instance work."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock


class StrategyInstanceKeyedMutexRegistry:
    """Retain one non-reentrant lock per exact strategy-instance key."""

    def __init__(self) -> None:
        self._registry_guard = Lock()
        self._locks: dict[str, Lock] = {}

    @contextmanager
    def hold(self, strategy_instance_id: str) -> Iterator[None]:
        """Hold the exact key's critical section for the context lifetime."""
        _require_strategy_instance_id(strategy_instance_id)
        with self._registry_guard:
            instance_lock = self._locks.setdefault(strategy_instance_id, Lock())
        with instance_lock:
            yield


def _require_strategy_instance_id(strategy_instance_id: str) -> None:
    if type(strategy_instance_id) is not str or len(strategy_instance_id) == 0:
        raise ValueError("strategy_instance_id must be a non-empty string")
