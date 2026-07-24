from pathlib import Path

from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    SelectedDeployment,
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal


class Catalog:
    def load_snapshot(self):
        return ("dep-a",)


class Selector:
    def select(self, *, event, snapshot):
        return (SelectedDeployment("dep-a", {"id": "dep-a"}),)


class Dispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def dispatch(self, unit):
        self.calls.append(unit.strategy_instance_id)
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)


def test_unavailable_processing_journal_does_not_stop_orchestration(tmp_path: Path) -> None:
    blocked_path = tmp_path / "blocked"
    blocked_path.mkdir()
    journal = JsonlProcessingJournal(
        blocked_path,
        event_id_factory=lambda: "event-1",
        timestamp_factory=lambda: "2026-07-21T00:00:00Z",
    )
    dispatcher = Dispatcher()
    orchestrator = CommittedBarOrchestrator(
        deployment_catalog=Catalog(),
        deployment_selector=Selector(),
        strategy_cycle_dispatcher=dispatcher,
        processing_journal=journal,
    )

    result = orchestrator.process(CommittedBarEvent("BTCUSDT.P", "5m", 123))

    assert dispatcher.calls == ["dep-a"]
    assert result.succeeded_count == 1
    assert journal.failure_count == 3
