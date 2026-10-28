"""`entry_cycle_ended` journaling in `StrategyRuntimeOrchestrator.process(...)`:
one event for an entry cycle that never filled and is gone from the state saved on this bar,
written after the durable save, and never for a kept, new or filled cycle."""

from dataclasses import dataclass, field, replace

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
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

_SID = "ema_pullback:abc"
_BAR = 1_800_000
_ENTRY = DesiredEntry("short", 900, "81650.4", "81963.2", "79929.8", "x")


@dataclass
class _Recorder:
    calls: list[tuple[str, object]] = field(default_factory=list)


class _RecordingRepository(InMemoryStrategyInstanceRuntimeStateRepository):
    def __init__(self, recorder: _Recorder) -> None:
        super().__init__()
        self._recorder = recorder

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self._recorder.calls.append(("save", None))
        return super().save(state)


class _Journal:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def entry_cycle_ended(self, **fields: object) -> None:
        self._recorder.calls.append(("journal", fields))


class _Resolver:
    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        return PositionResolvedStrategyInstanceRuntimeState(state, False, None, None)


class _Router:
    def route(self, item: PositionResolvedStrategyInstance) -> LiveEntryProjectedStrategyInstance:
        return LiveEntryProjectedStrategyInstance(item, _ENTRY)


class _Reconciliation:
    """Returns the state the reconciliation step is told to produce."""

    def __init__(self, result: StrategyInstanceRuntimeState | None) -> None:
        self.result = result

    def execute(
        self, projection: LiveEntryProjectedStrategyInstance
    ) -> StrategyInstanceRuntimeState:
        if self.result is None:
            return projection.source.resolved_state.runtime_state
        return self.result


def _cycle(cycle_id: str, *, filled: bool = False) -> CurrentTradeCycle:
    frozen = FrozenExecutedEntryContext(_ENTRY, 1_000, 900) if filled else None
    return CurrentTradeCycle(cycle_id, AppliedEntryPackage(_ENTRY, "0.001"), frozen)


def _unit() -> StrategyBarProcessingUnit[DeploymentSpecification]:
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
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", _BAR),
    )


def _run(
    source_cycle: CurrentTradeCycle | None,
    result_cycle: CurrentTradeCycle | None | str,
) -> list[tuple[str, object]]:
    """Process one bar; `result_cycle == "unchanged"` makes the step return the source state."""
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    state = repository.get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id=_SID,
            strategy_id="ema_pullback",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={"ema": 200},
            source_path="/specs/a.json",
        )
    )
    source = repository.save(replace(state, current_trade_cycle=source_cycle))
    recorder.calls.clear()
    result = (
        None if result_cycle == "unchanged" else replace(source, current_trade_cycle=result_cycle)  # type: ignore[arg-type]
    )
    StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=_Resolver(),  # type: ignore[arg-type]
        use_case_router=_Router(),  # type: ignore[arg-type]
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=_Reconciliation(result),  # type: ignore[arg-type]
        position_management_orchestrator=None,  # type: ignore[arg-type]
        entry_cycle_ended_journal=_Journal(recorder),  # type: ignore[arg-type]
    ).process(_unit())
    return recorder.calls


_CANCELLED = {
    "strategy_instance_id": _SID,
    "trade_cycle_id": "cycle-1",
    "bar_open_time_ms": _BAR,
    "reason": "cancelled",
}


def test_confirmed_cancel_journals_after_the_save() -> None:
    assert _run(_cycle("cycle-1"), None) == [("save", None), ("journal", _CANCELLED)]


def test_replace_journals_the_old_cycle_once() -> None:
    assert _run(_cycle("cycle-1"), _cycle("cycle-2")) == [("save", None), ("journal", _CANCELLED)]


def test_kept_cycle_writes_nothing() -> None:
    assert _run(_cycle("cycle-1"), "unchanged") == []
    assert _run(_cycle("cycle-1"), _cycle("cycle-1")) == []


def test_new_cycle_from_flat_writes_nothing() -> None:
    assert _run(None, _cycle("cycle-1")) == [("save", None)]


def test_flat_stays_flat_writes_nothing() -> None:
    assert _run(None, "unchanged") == []


def test_removed_cycle_that_filled_writes_nothing() -> None:
    assert _run(_cycle("cycle-1", filled=True), None) == [("save", None)]
