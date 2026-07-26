from unittest.mock import patch

from strategy_runtime.runtime.state.identity import (
    TradeCycleIdFactory,
    new_trade_cycle_id,
)
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)


def reserve_identity(factory: TradeCycleIdFactory) -> str:
    return factory()


def test_production_trade_cycle_ids_are_non_empty_and_distinct() -> None:
    first = new_trade_cycle_id()
    second = new_trade_cycle_id()

    assert first
    assert second
    assert first != second


def test_trade_cycle_id_factory_is_deterministically_injectable() -> None:
    generated = iter(("cycle-a", "cycle-b"))

    def factory() -> str:
        return next(generated)

    injected: TradeCycleIdFactory = factory

    assert reserve_identity(injected) == "cycle-a"
    assert reserve_identity(injected) == "cycle-b"


def test_initial_registration_does_not_generate_a_trade_cycle_identity() -> None:
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id="instance",
        strategy_id="strategy",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={},
        source_path="a.json",
    )

    with patch(
        "strategy_runtime.runtime.state.identity.new_trade_cycle_id",
        side_effect=AssertionError("must not be called"),
    ):
        state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(request)

    assert state.current_trade_cycle is None
