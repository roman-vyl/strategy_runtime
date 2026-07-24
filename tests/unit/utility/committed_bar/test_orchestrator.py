from dataclasses import dataclass
from typing import Any

import pytest

from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    CommittedBarPreparationError,
    SelectedDeployment,
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
    StrategyCycleDispatchStatus,
    UpstreamOrchestrationStage,
)


@dataclass(frozen=True, slots=True)
class Deployment:
    name: str


class Catalog:
    def __init__(
        self, calls: list[str], *, value: object = "snapshot", error: Exception | None = None
    ):
        self.calls = calls
        self.value = value
        self.error = error
        self.call_count = 0

    def load_snapshot(self) -> object:
        self.calls.append("catalog")
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return self.value


class Selector:
    def __init__(
        self,
        calls: list[str],
        *,
        selected: tuple[SelectedDeployment[Deployment], ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.selected = selected
        self.error = error
        self.call_count = 0
        self.arguments: list[tuple[CommittedBarEvent, object]] = []

    def select(
        self,
        *,
        event: CommittedBarEvent,
        snapshot: object,
    ) -> tuple[SelectedDeployment[Deployment], ...]:
        self.calls.append("selection")
        self.call_count += 1
        self.arguments.append((event, snapshot))
        if self.error is not None:
            raise self.error
        return self.selected


class Dispatcher:
    def __init__(
        self,
        calls: list[str],
        *,
        failing_ids: frozenset[str] = frozenset(),
        mismatched_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.calls = calls
        self.failing_ids = failing_ids
        self.mismatched_ids = mismatched_ids
        self.units: list[StrategyBarProcessingUnit[Deployment]] = []

    def dispatch(
        self,
        unit: StrategyBarProcessingUnit[Deployment],
    ) -> StrategyCycleDispatchOutcome:
        self.calls.append(f"dispatch:{unit.strategy_instance_id}")
        self.units.append(unit)
        if unit.strategy_instance_id in self.failing_ids:
            raise RuntimeError(f"failed {unit.strategy_instance_id}")
        if unit.strategy_instance_id in self.mismatched_ids:
            return StrategyCycleDispatchOutcome.succeeded("other")
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)


class Journal:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.failed_stages: list[str] = []
        self.outcomes: list[StrategyCycleDispatchOutcome] = []
        self.completed: list[Any] = []

    def orchestration_started(
        self,
        *,
        event: CommittedBarEvent,
    ) -> None:
        self.calls.append("journal:started")

    def orchestration_failed(
        self,
        *,
        event: CommittedBarEvent,
        stage: str,
        error: Exception,
    ) -> None:
        self.calls.append(f"journal:failed:{stage}")
        self.failed_stages.append(stage)

    def strategy_cycle_outcome(
        self,
        *,
        event: CommittedBarEvent,
        outcome: StrategyCycleDispatchOutcome,
    ) -> None:
        self.calls.append(f"journal:outcome:{outcome.strategy_instance_id}")
        self.outcomes.append(outcome)

    def orchestration_completed(
        self,
        *,
        event: CommittedBarEvent,
        result: Any,
    ) -> None:
        self.calls.append("journal:completed")
        self.completed.append(result)


def _event() -> CommittedBarEvent:
    return CommittedBarEvent(
        instrument="BTCUSDT.P",
        timeframe="5m",
        open_time_ms=1_784_106_300_000,
    )


def _build(
    *,
    selected: tuple[SelectedDeployment[Deployment], ...] = (),
    catalog_error: Exception | None = None,
    selection_error: Exception | None = None,
    failing_ids: frozenset[str] = frozenset(),
    mismatched_ids: frozenset[str] = frozenset(),
) -> tuple[
    CommittedBarOrchestrator[object, Deployment],
    list[str],
    Catalog,
    Selector,
    Dispatcher,
    Journal,
]:
    calls: list[str] = []
    catalog = Catalog(calls, error=catalog_error)
    selector = Selector(calls, selected=selected, error=selection_error)
    dispatcher = Dispatcher(
        calls,
        failing_ids=failing_ids,
        mismatched_ids=mismatched_ids,
    )
    journal = Journal(calls)
    orchestrator = CommittedBarOrchestrator[object, Deployment](
        deployment_catalog=catalog,
        deployment_selector=selector,
        strategy_cycle_dispatcher=dispatcher,
        processing_journal=journal,
    )
    return orchestrator, calls, catalog, selector, dispatcher, journal


def test_exact_call_order_and_single_upstream_calls() -> None:
    selected = (
        SelectedDeployment("strategy-b", Deployment("B")),
        SelectedDeployment("strategy-a", Deployment("A")),
    )
    orchestrator, calls, catalog, selector, dispatcher, journal = _build(selected=selected)

    result = orchestrator.process(_event())

    assert calls == [
        "journal:started",
        "catalog",
        "selection",
        "dispatch:strategy-a",
        "journal:outcome:strategy-a",
        "dispatch:strategy-b",
        "journal:outcome:strategy-b",
        "journal:completed",
    ]
    assert catalog.call_count == 1
    assert selector.call_count == 1
    assert [unit.strategy_instance_id for unit in dispatcher.units] == [
        "strategy-a",
        "strategy-b",
    ]
    assert result.selected_count == 2
    assert result.attempted_count == 2
    assert result.succeeded_count == 2
    assert result.failed_count == 0
    assert journal.completed == [result]


def test_zero_selected_deployments_returns_empty_result() -> None:
    orchestrator, calls, _, _, dispatcher, _ = _build()

    result = orchestrator.process(_event())

    assert dispatcher.units == []
    assert result.outcomes == ()
    assert result.selected_count == 0
    assert result.attempted_count == 0
    assert calls[-1] == "journal:completed"


def test_processing_unit_contains_only_established_orchestration_data() -> None:
    deployment = Deployment("A")
    orchestrator, _, _, _, dispatcher, _ = _build(
        selected=(SelectedDeployment("strategy-a", deployment),)
    )
    event = _event()

    orchestrator.process(event)

    assert dispatcher.units == [
        StrategyBarProcessingUnit(
            strategy_instance_id="strategy-a",
            deployment=deployment,
            committed_bar=event,
        )
    ]
    assert set(StrategyBarProcessingUnit.__dataclass_fields__) == {
        "strategy_instance_id",
        "deployment",
        "committed_bar",
    }


def test_one_dispatch_failure_does_not_stop_remaining_units() -> None:
    selected = tuple(
        SelectedDeployment(identity, Deployment(identity)) for identity in ("a", "b", "c")
    )
    orchestrator, _, _, _, dispatcher, journal = _build(
        selected=selected,
        failing_ids=frozenset({"b"}),
    )

    result = orchestrator.process(_event())

    assert [unit.strategy_instance_id for unit in dispatcher.units] == ["a", "b", "c"]
    assert result.succeeded_count == 2
    assert result.failed_count == 1
    assert result.outcomes[1].status is StrategyCycleDispatchStatus.FAILED
    assert result.outcomes[1].error_code == "strategy_cycle_dispatch_failed"
    assert journal.outcomes == list(result.outcomes)


def test_mismatched_dispatch_outcome_is_recorded_as_failed() -> None:
    orchestrator, _, _, _, _, _ = _build(
        selected=(SelectedDeployment("a", Deployment("A")),),
        mismatched_ids=frozenset({"a"}),
    )

    result = orchestrator.process(_event())

    assert result.failed_count == 1
    assert result.outcomes[0].error_code == "strategy_cycle_outcome_identity_mismatch"


@pytest.mark.parametrize(
    ("error_field", "expected_stage", "expected_calls"),
    [
        (
            "catalog_error",
            UpstreamOrchestrationStage.DEPLOYMENT_CATALOG,
            ["journal:started", "catalog", "journal:failed:deployment_catalog"],
        ),
        (
            "selection_error",
            UpstreamOrchestrationStage.DEPLOYMENT_SELECTION,
            [
                "journal:started",
                "catalog",
                "selection",
                "journal:failed:deployment_selection",
            ],
        ),
    ],
)
def test_upstream_failure_stops_fan_out(
    error_field: str,
    expected_stage: UpstreamOrchestrationStage,
    expected_calls: list[str],
) -> None:
    kwargs = {error_field: RuntimeError("upstream failed")}
    orchestrator, calls, _, _, dispatcher, journal = _build(**kwargs)

    with pytest.raises(CommittedBarPreparationError) as captured:
        orchestrator.process(_event())

    assert captured.value.stage is expected_stage
    assert dispatcher.units == []
    assert journal.completed == []
    assert calls == expected_calls
