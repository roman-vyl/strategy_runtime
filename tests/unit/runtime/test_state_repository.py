from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import MappingProxyType
from typing import cast

import pytest

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.errors import (
    StrategyInstanceIdentityConflict,
    StrategyInstanceRegistrationConflict,
    StrategyInstanceStateNotFound,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)


def test_concurrent_equivalent_creation_returns_one_aggregate_object() -> None:
    worker_count = 16
    start = Barrier(worker_count)
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id="ema_pullback:abc",
        strategy_id="ema_pullback",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="ema-pullback.json",
    )

    def get_or_create(_: int):
        start.wait()
        return repository.get_or_create(request)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        states = tuple(executor.map(get_or_create, range(worker_count)))

    assert all(state is states[0] for state in states)
    assert states[0].current_trade_cycle is None


def make_request(
    *,
    strategy_instance_id: str = "ema_pullback:abc",
    strategy_id: str = "ema_pullback",
    instrument: str = "BTCUSDT.P",
    base_timeframe: str = "5m",
    raw_spec=None,
    source_path: str = "ema-pullback.json",
) -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=strategy_instance_id,
        strategy_id=strategy_id,
        instrument=instrument,
        base_timeframe=base_timeframe,
        raw_spec=raw_spec or {"ema": 200},
        source_path=source_path,
    )


def test_same_authoritative_instance_id_returns_the_same_aggregate() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    first = repository.get_or_create(make_request())

    second = repository.get_or_create(
        make_request(
            instrument="ETHUSDT.P",
            base_timeframe="1h",
            raw_spec={"ema": 300},
            source_path="different.json",
        )
    )

    assert second is first
    assert second.registered_spec_snapshot.instrument == "BTCUSDT.P"
    assert second.registered_spec_snapshot.raw_spec["ema"] == 200
    assert second.risk_multiplier == "1"


def test_different_derived_instance_ids_create_different_aggregates() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()

    first = repository.get_or_create(make_request(strategy_instance_id="ema_pullback:abc"))
    second = repository.get_or_create(make_request(strategy_instance_id="ema_pullback:def"))

    assert second is not first
    assert second.strategy_instance_id != first.strategy_instance_id


def test_registered_snapshot_owns_raw_spec_freezing_not_transport_request() -> None:
    raw_spec = {"ema": {"periods": [20, 200]}}
    request = make_request(raw_spec=raw_spec)
    assert not isinstance(request.raw_spec, MappingProxyType)

    state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(request)
    raw_spec["ema"]["periods"].append(300)

    assert request.raw_spec["ema"]["periods"] == [20, 200, 300]
    assert state.registered_spec_snapshot.raw_spec["ema"]["periods"] == (20, 200)
    assert isinstance(state.registered_spec_snapshot.raw_spec, MappingProxyType)


def test_existing_instance_keeps_defensive_strategy_id_check() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    repository.get_or_create(make_request())

    with pytest.raises(StrategyInstanceIdentityConflict):
        repository.get_or_create(make_request(strategy_id="different"))


def test_missing_state_registration_uses_canonical_risk_without_creating_cycle() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()

    state = repository.get_or_create(make_request())

    assert state.risk_multiplier == "1"
    assert state.current_trade_cycle is None


def test_get_returns_existing_state_or_none_without_creation() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    assert repository.get("missing") is None

    state = repository.get_or_create(make_request())

    assert repository.get(state.strategy_instance_id) is state


@pytest.mark.parametrize("identity", [None, 1, ""])
def test_get_rejects_invalid_identity(identity: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        InMemoryStrategyInstanceRuntimeStateRepository().get(cast("str", identity))


def test_save_replaces_the_complete_registered_aggregate() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    initial = repository.get_or_create(make_request())
    cycle = CurrentTradeCycle(
        trade_cycle_id="cycle-1",
        applied_entry_package=AppliedEntryPackage(
            applied_desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
            calculated_quantity="0.0100",
        ),
    )
    replacement = replace(
        initial,
        risk_multiplier="2.500",
        current_trade_cycle=cycle,
    )

    saved = repository.save(replacement)

    assert saved is replacement
    assert repository.get(initial.strategy_instance_id) is replacement
    assert saved.risk_multiplier == "2.500"
    assert saved.current_trade_cycle is cycle


def test_save_rejects_unregistered_identity_without_creating_it() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(
        make_request(strategy_instance_id="unregistered")
    )

    with pytest.raises(StrategyInstanceStateNotFound):
        repository.save(state)

    assert repository.get("unregistered") is None


def test_save_rejects_strategy_identity_change_and_preserves_existing() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    initial = repository.get_or_create(make_request())

    with pytest.raises(StrategyInstanceIdentityConflict):
        repository.save(replace(initial, strategy_id="other"))

    assert repository.get(initial.strategy_instance_id) is initial


def test_save_rejects_registered_snapshot_change_and_preserves_existing() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    initial = repository.get_or_create(make_request())
    changed_snapshot = RegisteredSpecSnapshot(
        instrument="ETHUSDT.P",
        base_timeframe="1h",
        raw_spec={"ema": 300},
        source_path="other.json",
    )

    with pytest.raises(StrategyInstanceRegistrationConflict):
        repository.save(replace(initial, registered_spec_snapshot=changed_snapshot))

    assert repository.get(initial.strategy_instance_id) is initial


def test_repeated_discovery_preserves_saved_risk_and_complete_cycle() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    initial = repository.get_or_create(make_request())
    cycle = _complete_cycle("cycle-1", quantity="0.01")
    saved = repository.save(replace(initial, risk_multiplier="1.25", current_trade_cycle=cycle))

    rediscovered = repository.get_or_create(make_request())

    assert rediscovered is saved
    assert rediscovered.risk_multiplier == "1.25"
    assert rediscovered.current_trade_cycle is cycle


def test_concurrent_get_observes_only_complete_saved_aggregates() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    initial = repository.get_or_create(make_request())
    first = replace(
        initial,
        risk_multiplier="2",
        current_trade_cycle=_complete_cycle("cycle-a", quantity="0.02"),
    )
    second = replace(
        initial,
        risk_multiplier="3",
        current_trade_cycle=_complete_cycle("cycle-b", quantity="0.03"),
    )
    start = Barrier(4)

    def writer(state: StrategyInstanceRuntimeState) -> None:
        start.wait()
        for _ in range(200):
            repository.save(state)

    def reader() -> None:
        start.wait()
        for _ in range(200):
            observed = repository.get(initial.strategy_instance_id)
            assert observed is not None
            assert observed in (initial, first, second)
            if observed is first:
                assert observed.risk_multiplier == "2"
                assert observed.current_trade_cycle is not None
                assert observed.current_trade_cycle.trade_cycle_id == "cycle-a"
            if observed is second:
                assert observed.risk_multiplier == "3"
                assert observed.current_trade_cycle is not None
                assert observed.current_trade_cycle.trade_cycle_id == "cycle-b"

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = (
            executor.submit(writer, first),
            executor.submit(writer, second),
            executor.submit(reader),
            executor.submit(reader),
        )
        for future in futures:
            future.result()


def _complete_cycle(trade_cycle_id: str, *, quantity: str) -> CurrentTradeCycle:
    return CurrentTradeCycle(
        trade_cycle_id=trade_cycle_id,
        applied_entry_package=AppliedEntryPackage(
            applied_desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
            calculated_quantity=quantity,
        ),
    )
