from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import MappingProxyType

import pytest

from strategy_runtime.runtime.state.errors import StrategyInstanceIdentityConflict
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
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
