"""`live_entry_evaluated` journaling in `StrategyRuntimeOrchestrator.process(...)`:
one event per successful Engine live-entry answer (`null` included), written
before entry reconciliation, and never on a path that did not evaluate live entry."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation import (
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import (
    CloseSignal,
    DesiredProtection,
    EngineDesiredProtectionText,
    PositionManagementRecipe,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
    StrategyUseCaseProjectedInstance,
)
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingEntryRecovery,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal
from strategy_runtime.utility.processing_journal.models import JsonValue

_SID = "ema_pullback:abc"


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100.50", "99", "103.25", "runner")


def _request() -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=_SID,
        strategy_id="ema_pullback",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )


def _unit(bar_open_time_ms: int = 1000) -> StrategyBarProcessingUnit[DeploymentSpecification]:
    deployment = DeploymentSpecification(
        strategy_instance_id=_SID,
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="ema_pullback",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )
    return StrategyBarProcessingUnit(
        strategy_instance_id=_SID,
        deployment=deployment,
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", bar_open_time_ms),
    )


@dataclass
class _Recorder:
    calls: list[tuple[str, object]] = field(default_factory=list)


class _FakeJournal:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def live_entry_evaluated(
        self,
        *,
        strategy_instance_id: str,
        instrument: str,
        timeframe: str,
        bar_open_time_ms: int,
        desired_entry: Mapping[str, JsonValue] | None,
    ) -> None:
        self._recorder.calls.append(
            (
                "journal",
                (strategy_instance_id, instrument, timeframe, bar_open_time_ms, desired_entry),
            )
        )


class _Resolver:
    def resolve(self, state: StrategyInstanceRuntimeState) -> object:
        return PositionResolvedStrategyInstanceRuntimeState(state, False, None, None)


class _Router:
    def __init__(
        self,
        *,
        desired_entry: DesiredEntry | None = None,
        engine_error: Exception | None = None,
        open_trade: bool = False,
    ) -> None:
        self._desired_entry = desired_entry
        self._engine_error = engine_error
        self._open_trade = open_trade

    def route(self, item: PositionResolvedStrategyInstance) -> StrategyUseCaseProjectedInstance:
        if self._engine_error is not None:
            raise self._engine_error
        if self._open_trade:
            recipe = PositionManagementRecipe(
                DesiredProtection("99", "103"),
                CloseSignal(active=False),
                {},
                EngineDesiredProtectionText("99", "103"),
            )
            return OpenTradeProjectedStrategyInstance(item, recipe)
        return LiveEntryProjectedStrategyInstance(item, self._desired_entry)


class _Reconciliation:
    def __init__(self, recorder: _Recorder, error: Exception | None = None) -> None:
        self._recorder = recorder
        self._error = error

    def execute(
        self, projection: LiveEntryProjectedStrategyInstance
    ) -> StrategyInstanceRuntimeState:
        self._recorder.calls.append(("reconciliation", None))
        if self._error is not None:
            raise self._error
        return projection.source.resolved_state.runtime_state


class _PositionManagement:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def execute(
        self, projection: OpenTradeProjectedStrategyInstance
    ) -> StrategyInstanceRuntimeState:
        self._recorder.calls.append(("position_management", None))
        return projection.source.resolved_state.runtime_state

    def execute_with_closure(
        self, projection: OpenTradeProjectedStrategyInstance
    ) -> tuple[StrategyInstanceRuntimeState, None]:
        return self.execute(projection), None


def _build(
    recorder: _Recorder,
    router: _Router,
    *,
    journal: object | None = None,
    reconciliation_error: Exception | None = None,
    state: StrategyInstanceRuntimeState | None = None,
) -> StrategyRuntimeOrchestrator:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    if state is not None:
        repository.get_or_create(_request())
        repository.save(state)
    return StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=_Resolver(),  # type: ignore[arg-type]
        use_case_router=router,  # type: ignore[arg-type]
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=_Reconciliation(  # type: ignore[arg-type]
            recorder, reconciliation_error
        ),
        position_management_orchestrator=_PositionManagement(recorder),  # type: ignore[arg-type]
        live_entry_journal=journal or _FakeJournal(recorder),  # type: ignore[arg-type]
    )


_ENTRY_PAYLOAD = {
    "side": "long",
    "source_plan_bar_open_time_ms": 900,
    "planned_entry_price": "100.5",
    "initial_stop_price": "99",
    "initial_take_price": "103.25",
    "locked_exit_profile": "runner",
}


def test_non_null_desired_entry_is_journaled_before_reconciliation() -> None:
    recorder = _Recorder()
    orch = _build(recorder, _Router(desired_entry=_desired_entry()))

    orch.process(_unit(1000))

    assert recorder.calls == [
        ("journal", (_SID, "BTCUSDT.P", "5m", 1000, _ENTRY_PAYLOAD)),
        ("reconciliation", None),
    ]


def test_null_desired_entry_is_journaled() -> None:
    recorder = _Recorder()
    orch = _build(recorder, _Router(desired_entry=None))

    orch.process(_unit(1300))

    assert recorder.calls[0] == ("journal", (_SID, "BTCUSDT.P", "5m", 1300, None))


def test_event_survives_a_failing_reconciliation_step() -> None:
    recorder = _Recorder()
    orch = _build(
        recorder,
        _Router(desired_entry=_desired_entry()),
        reconciliation_error=RuntimeError("abi down"),
    )

    with pytest.raises(RuntimeError, match="abi down"):
        orch.process(_unit())

    assert [name for name, _ in recorder.calls] == ["journal", "reconciliation"]


def test_no_event_when_engine_live_entry_fails() -> None:
    recorder = _Recorder()
    orch = _build(recorder, _Router(engine_error=RuntimeError("engine down")))

    with pytest.raises(RuntimeError, match="engine down"):
        orch.process(_unit())

    assert recorder.calls == []


def test_no_event_on_pending_recovery_skip() -> None:
    recorder = _Recorder()
    base = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(_request())
    state = replace(base, pending_entry_recovery=PendingEntryRecovery("cycle-new"))
    orch = _build(recorder, _Router(desired_entry=_desired_entry()), state=state)

    orch.process(_unit())

    assert recorder.calls == []


def test_no_event_on_open_trade_path() -> None:
    recorder = _Recorder()
    orch = _build(recorder, _Router(open_trade=True))

    orch.process(_unit())

    assert recorder.calls == [("position_management", None)]


def test_same_bar_evaluated_twice_is_journaled_twice() -> None:
    recorder = _Recorder()
    orch = _build(recorder, _Router(desired_entry=None))

    orch.process(_unit(1000))
    orch.process(_unit(1000))

    assert [name for name, _ in recorder.calls] == [
        "journal",
        "reconciliation",
        "journal",
        "reconciliation",
    ]


def test_unwritable_journal_does_not_change_the_bar_outcome(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    journal = JsonlProcessingJournal(
        blocked,
        event_id_factory=lambda: "event-1",
        timestamp_factory=lambda: "2026-07-21T00:00:00Z",
    )
    recorder = _Recorder()
    orch = _build(recorder, _Router(desired_entry=_desired_entry()), journal=journal)

    state = orch.process(_unit())

    assert state.strategy_instance_id == _SID
    assert journal.failure_count == 1
    assert recorder.calls == [("reconciliation", None)]


def test_real_journal_line_for_a_live_entry_bar(tmp_path: Path) -> None:
    path = tmp_path / "journal" / "runtime.jsonl"
    journal = JsonlProcessingJournal(
        path,
        event_id_factory=lambda: "event-1",
        timestamp_factory=lambda: "2026-07-21T00:00:00Z",
    )
    orch = _build(_Recorder(), _Router(desired_entry=_desired_entry()), journal=journal)

    orch.process(_unit(1000))

    record = json.loads(path.read_text())
    assert record["event_type"] == "live_entry_evaluated"
    assert record["strategy_instance_id"] == _SID
    assert record["payload"]["desired_entry"] == _ENTRY_PAYLOAD


class _AppliedExecutionPort:
    def execute(
        self, command: EntryReconciliationCommand, source_state: StrategyInstanceRuntimeState
    ) -> EntryAppliedConfirmation:
        assert command.desired_entry is not None
        return EntryAppliedConfirmation(
            command.strategy_instance_id,
            command.trade_cycle_id,
            command.desired_entry,
            "0.001",
            trigger_price="100.5",
            stop_loss="99",
            take_profit="103.25",
            quantity="0.001",
            order_link_id="link-1",
            order_id="bybit-1",
        )


def test_applied_record_carries_the_bar_of_the_same_evaluation(tmp_path: Path) -> None:
    path = tmp_path / "journal" / "runtime.jsonl"
    journal = JsonlProcessingJournal(
        path,
        event_id_factory=lambda: "event-1",
        timestamp_factory=lambda: "2026-07-21T00:00:00Z",
    )
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    orch = StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=_Resolver(),  # type: ignore[arg-type]
        use_case_router=_Router(desired_entry=_desired_entry()),  # type: ignore[arg-type]
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
            lambda: "cycle-1",
            _AppliedExecutionPort(),
            repository,
            entry_applied_journal=journal,
        ),
        position_management_orchestrator=_PositionManagement(_Recorder()),  # type: ignore[arg-type]
        live_entry_journal=journal,
    )

    orch.process(_unit(1300))

    evaluated, applied = (json.loads(line) for line in path.read_text().splitlines())
    assert evaluated["event_type"] == "live_entry_evaluated"
    assert applied["event_type"] == "entry_package_applied"
    assert applied["strategy_instance_id"] == evaluated["strategy_instance_id"] == _SID
    assert (
        applied["payload"]["bar_open_time_ms"] == evaluated["payload"]["bar_open_time_ms"] == 1300
    )
    assert applied["payload"]["trade_cycle_id"] == "cycle-1"
    assert (applied["payload"]["order_link_id"], applied["payload"]["order_id"]) == (
        "link-1",
        "bybit-1",
    )
