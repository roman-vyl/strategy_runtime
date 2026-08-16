"""The pending-entry-recovery guard in `StrategyRuntimeOrchestrator.process(...)`
(task 4.1 / 8.7): a non-null `pending_entry_recovery` defers the entire
pipeline, before even the open-position resolver -- an unguarded lookup
against an ABI-side unresolved status is exactly the BTC-class 500 lockup
this guard exists to prevent."""

from dataclasses import replace

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
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
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification

_SID = "ema_pullback:abc"


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100", "99", "103", "runner")


def _request(sid: str = _SID) -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=sid,
        strategy_id="ema_pullback",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )


def _processing_unit(sid: str = _SID) -> StrategyBarProcessingUnit[DeploymentSpecification]:
    deployment = DeploymentSpecification(
        strategy_instance_id=sid,
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="ema_pullback",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )
    return StrategyBarProcessingUnit(
        strategy_instance_id=sid,
        deployment=deployment,
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 1000),
    )


class _AssertNotCalled:
    """A collaborator that fails the test the instant it is ever invoked."""

    def __getattr__(self, name: str) -> object:
        def _fail(*_args: object, **_kwargs: object) -> object:
            raise AssertionError(f"{name} must not be called while pending_entry_recovery is set")

        return _fail


class _RecordingRepository:
    def __init__(self, state: StrategyInstanceRuntimeState) -> None:
        self._state = state
        self.save_calls = 0

    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState:
        return self._state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        return self._state

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.save_calls += 1
        self._state = state
        return state

    def list_ids_with_pending_entry_recovery(self) -> tuple[str, ...]:
        return ()


def _pending_state(
    *, current_trade_cycle: CurrentTradeCycle | None
) -> StrategyInstanceRuntimeState:
    state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(_request())
    return replace(
        state,
        current_trade_cycle=current_trade_cycle,
        pending_entry_recovery=PendingEntryRecovery(
            current_trade_cycle.trade_cycle_id if current_trade_cycle is not None else "cycle-new"
        ),
    )


def _build_orchestrator(repository: _RecordingRepository) -> StrategyRuntimeOrchestrator:
    return StrategyRuntimeOrchestrator(
        state_repository=repository,  # type: ignore[arg-type]
        open_position_resolver=_AssertNotCalled(),  # type: ignore[arg-type]
        use_case_router=_AssertNotCalled(),  # type: ignore[arg-type]
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=_AssertNotCalled(),  # type: ignore[arg-type]
        position_management_orchestrator=_AssertNotCalled(),  # type: ignore[arg-type]
    )


def test_guard_returns_the_unchanged_state_before_the_open_position_resolver() -> None:
    """An uncertain removal leaves current_trade_cycle set: an unguarded
    open-position lookup would reproduce the BTC-class 500 lockup."""
    cycle = CurrentTradeCycle("cycle-1", AppliedEntryPackage(_desired_entry(), "0.01"))
    state = _pending_state(current_trade_cycle=cycle)
    repository = _RecordingRepository(state)
    orch = _build_orchestrator(repository)

    result = orch.process(_processing_unit())

    assert result == state
    assert repository.save_calls == 0


def test_guard_returns_the_unchanged_state_for_an_uncertain_create_too() -> None:
    state = _pending_state(current_trade_cycle=None)
    repository = _RecordingRepository(state)
    orch = _build_orchestrator(repository)

    result = orch.process(_processing_unit())

    assert result == state
    assert repository.save_calls == 0


def test_normal_bar_path_proceeds_when_pending_entry_recovery_is_null() -> None:
    """Sanity check that the guard is conditional, not unconditional: an
    instance with no pending marker still reaches the open-position resolver
    (which here is the assert-not-called collaborator, proving it *was*
    reached by the AssertionError propagating out of process())."""
    state = InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(_request())
    assert state.pending_entry_recovery is None
    repository = _RecordingRepository(state)
    orch = _build_orchestrator(repository)

    try:
        orch.process(_processing_unit())
    except AssertionError as exc:
        assert "resolve" in str(exc)
    else:
        raise AssertionError("expected the unguarded path to reach the open-position resolver")


def test_dispatch_reports_a_guarded_deferral_as_an_ordinary_successful_outcome() -> None:
    state = _pending_state(current_trade_cycle=None)
    repository = _RecordingRepository(state)
    orch = _build_orchestrator(repository)

    outcome = orch.dispatch(_processing_unit())

    assert outcome == StrategyCycleDispatchOutcome.succeeded(_SID)
