from dataclasses import FrozenInstanceError

import pytest

from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrationResult,
    SelectedDeployment,
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
)


def test_orchestration_models_are_immutable() -> None:
    event = CommittedBarEvent("BTCUSDT.P", "5m", 1)
    selected = SelectedDeployment("strategy-a", object())
    unit = StrategyBarProcessingUnit(
        strategy_instance_id=selected.strategy_instance_id,
        deployment=selected.deployment,
        committed_bar=event,
    )

    with pytest.raises(FrozenInstanceError):
        event.instrument = "ETHUSDT.P"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        unit.strategy_instance_id = "other"  # type: ignore[misc]


def test_aggregate_result_validates_counts() -> None:
    outcome = StrategyCycleDispatchOutcome.succeeded("strategy-a")

    with pytest.raises(ValueError, match="attempted_count"):
        CommittedBarOrchestrationResult(
            selected_count=1,
            attempted_count=0,
            succeeded_count=0,
            failed_count=0,
            outcomes=(outcome,),
        )
