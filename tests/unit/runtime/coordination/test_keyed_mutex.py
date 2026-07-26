from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

from strategy_runtime.runtime.coordination import (
    StrategyInstanceKeyedMutexRegistry,
)


def test_same_key_critical_sections_never_overlap() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()
    start = Barrier(8)
    observation_guard = Lock()
    active = 0
    peak_active = 0

    def worker() -> None:
        nonlocal active, peak_active
        start.wait()
        with registry.hold("instance"):
            with observation_guard:
                active += 1
                peak_active = max(peak_active, active)
            with observation_guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=8) as executor:
        tuple(executor.map(lambda _: worker(), range(8)))

    assert peak_active == 1


def test_different_keys_can_overlap() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()
    both_entered = Barrier(2, timeout=2)

    def worker(key: str) -> None:
        with registry.hold(key):
            both_entered.wait()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, key) for key in ("a", "b")]
        for future in futures:
            future.result(timeout=3)


def test_concurrent_first_use_of_same_key_selects_one_shared_lock() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def first() -> None:
        with registry.hold("new-key"):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def second() -> None:
        assert first_entered.wait(timeout=2)
        with registry.hold("new-key"):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first)
        second_future = executor.submit(second)
        assert first_entered.wait(timeout=2)
        assert not second_entered.wait(timeout=0.05)
        release_first.set()
        first_future.result(timeout=3)
        second_future.result(timeout=3)

    assert second_entered.is_set()


def test_lock_is_released_when_context_raises() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()

    with pytest.raises(RuntimeError, match="boom"), registry.hold("instance"):
        raise RuntimeError("boom")

    with registry.hold("instance"):
        pass


@pytest.mark.parametrize("key", [None, 1, ""])
def test_invalid_key_is_rejected(key: object) -> None:
    registry = StrategyInstanceKeyedMutexRegistry()

    with (
        pytest.raises((TypeError, ValueError)),
        registry.hold(
            key  # type: ignore[arg-type]
        ),
    ):
        raise AssertionError("must not enter")


def test_exact_keys_are_not_trimmed_or_normalized() -> None:
    registry = StrategyInstanceKeyedMutexRegistry()
    both_entered = Barrier(2, timeout=2)

    def worker(key: str) -> None:
        with registry.hold(key):
            both_entered.wait()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, key) for key in ("instance", " instance ")]
        for future in futures:
            future.result(timeout=3)
