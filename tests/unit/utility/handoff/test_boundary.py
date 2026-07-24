from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
    StrategyCycleDispatchStatus,
)
from strategy_runtime.utility.handoff import StrategyCycleHandoffBoundary


def _unit() -> StrategyBarProcessingUnit[str]:
    return StrategyBarProcessingUnit(
        strategy_instance_id="deployment-a",
        deployment="spec",
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 123),
    )


def test_terminal_boundary_accepts_unit_without_downstream_sink() -> None:
    outcome = StrategyCycleHandoffBoundary[str]().dispatch(_unit())

    assert outcome.status is StrategyCycleDispatchStatus.SUCCEEDED
    assert outcome.strategy_instance_id == "deployment-a"


def test_boundary_hands_exact_unit_to_attached_future_sink() -> None:
    received = []
    unit = _unit()

    outcome = StrategyCycleHandoffBoundary[str](received.append).dispatch(unit)

    assert received == [unit]
    assert outcome.status is StrategyCycleDispatchStatus.SUCCEEDED


def test_sink_failure_is_left_for_committed_bar_orchestrator_to_isolate() -> None:
    def fail(_unit: StrategyBarProcessingUnit[str]) -> None:
        raise RuntimeError("downstream unavailable")

    boundary = StrategyCycleHandoffBoundary[str](fail)

    try:
        boundary.dispatch(_unit())
    except RuntimeError as error:
        assert str(error) == "downstream unavailable"
    else:
        raise AssertionError("sink failure must cross the boundary")
