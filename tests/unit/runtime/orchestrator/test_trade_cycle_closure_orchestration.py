"""Bar-path and pending-close handling of ABI-proven closures (runtime-trade-cycle-closure-v1)."""

from dataclasses import dataclass, field, replace

import pytest

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.position_management_execution import (
    PositionManagementExecutionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ClosePositionCommand,
    PositionClosedConfirmation,
)
from strategy_runtime.runtime.position_management_orchestrator import (
    PositionManagementOrchestrator,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import (
    CloseSignal,
    DesiredProtection,
    PositionManagementRecipe,
)
from strategy_runtime.runtime.routing.models import (
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingCloseRecovery,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
from strategy_runtime.runtime.uncertain_exchange_state_resolver.resolver import (
    UncertainExchangeStateResolver,
)
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification

_SID = "ema_pullback:abc"
_CYCLE = "cycle-1"
_BAR = 1_800_000


def _stop_closure(trade_cycle_id: str = _CYCLE) -> TradeCycleClosure:
    return TradeCycleClosure(_SID, trade_cycle_id, "stop_loss", "a34add42", None, "abi-ep-1")


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


@dataclass
class _Recorder:
    calls: list[tuple[str, object]] = field(default_factory=list)


class _RecordingRepository(InMemoryStrategyInstanceRuntimeStateRepository):
    def __init__(self, recorder: _Recorder) -> None:
        super().__init__()
        self._recorder = recorder

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self._recorder.calls.append(("save", state.current_trade_cycle is None))
        return super().save(state)


class _Journal:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def trade_cycle_closed(self, **fields: object) -> None:
        self._recorder.calls.append(("journal", fields))


def _state_with_cycle(
    repository: InMemoryStrategyInstanceRuntimeStateRepository,
    *,
    pending_close: bool = False,
) -> StrategyInstanceRuntimeState:
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
    package = AppliedEntryPackage(
        DesiredEntry("short", 900, "81650.4", "81963.2", "79929.8", "x"), "0.001"
    )
    return repository.save(
        replace(
            state,
            current_trade_cycle=CurrentTradeCycle(_CYCLE, package),
            pending_close_recovery=PendingCloseRecovery(_CYCLE) if pending_close else None,
        )
    )


class _Resolver:
    def __init__(self, **facts: object) -> None:
        self._facts = facts

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        return PositionResolvedStrategyInstanceRuntimeState(state, **self._facts)  # type: ignore[arg-type]


class _Router:
    def __init__(self, recorder: _Recorder, *, close: bool = False) -> None:
        self._recorder = recorder
        self._close = close

    def route(self, item: PositionResolvedStrategyInstance) -> object:
        self._recorder.calls.append(("engine", None))
        recipe = PositionManagementRecipe(
            DesiredProtection("81963.2", "79929.8"), CloseSignal(active=self._close), {}
        )
        return OpenTradeProjectedStrategyInstance(item, recipe)


class _ClosePort:
    def __init__(self, confirmation: PositionClosedConfirmation) -> None:
        self.confirmation = confirmation
        self.calls: list[ClosePositionCommand] = []

    def apply_protection(self, command: object) -> object:  # pragma: no cover - unused
        raise NotImplementedError

    def close_position(self, command: ClosePositionCommand) -> PositionClosedConfirmation:
        self.calls.append(command)
        return self.confirmation


class _NoEntry:
    def execute(self, projection: object) -> object:  # pragma: no cover - must not run
        raise AssertionError("no entry may be evaluated on a closure bar")


def _orchestrator(
    recorder: _Recorder,
    repository: InMemoryStrategyInstanceRuntimeStateRepository,
    resolver: _Resolver,
    *,
    close_port: _ClosePort | None = None,
    close: bool = False,
) -> StrategyRuntimeOrchestrator:
    return StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=resolver,  # type: ignore[arg-type]
        use_case_router=_Router(recorder, close=close),  # type: ignore[arg-type]
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=_NoEntry(),  # type: ignore[arg-type]
        position_management_orchestrator=PositionManagementOrchestrator(
            close_port or _ClosePort(PositionClosedConfirmation(_SID, _CYCLE)),  # type: ignore[arg-type]
            repository,
        ),
        trade_cycle_closed_journal=_Journal(recorder),  # type: ignore[arg-type]
    )


_STOP_RECORD = {
    "strategy_instance_id": _SID,
    "trade_cycle_id": _CYCLE,
    "bar_open_time_ms": _BAR,
    "reason": "stop_loss",
    "order_id": "a34add42",
    "order_link_id": None,
    "parent_order_link_id": "abi-ep-1",
}


def test_bar_with_closure_ends_the_cycle_before_engine_and_journals_after_save() -> None:
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    _state_with_cycle(repository)
    recorder.calls.clear()
    resolver = _Resolver(
        position_open=False,
        first_fill_at_ms=None,
        average_entry_price=None,
        closure=_stop_closure(),
    )

    result = _orchestrator(recorder, repository, resolver).process(_unit())

    assert result.current_trade_cycle is None
    assert result.pending_close_recovery is None
    assert recorder.calls == [("save", True), ("journal", _STOP_RECORD)]


def test_mismatched_closure_raises_and_changes_nothing() -> None:
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    before = _state_with_cycle(repository)
    recorder.calls.clear()
    resolver = _Resolver(
        position_open=False,
        first_fill_at_ms=None,
        average_entry_price=None,
        closure=_stop_closure("cycle-2"),
    )

    with pytest.raises(PositionManagementExecutionInvariantError):
        _orchestrator(recorder, repository, resolver).process(_unit())

    assert recorder.calls == []
    assert repository.get(_SID) == before


def test_bar_close_with_a_closure_journals_after_the_save() -> None:
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    _state_with_cycle(repository)
    recorder.calls.clear()
    resolver = _Resolver(
        position_open=True, first_fill_at_ms=1_200_000, average_entry_price="81660.6"
    )
    port = _ClosePort(PositionClosedConfirmation(_SID, _CYCLE, _stop_closure()))

    result = _orchestrator(recorder, repository, resolver, close_port=port, close=True).process(
        _unit()
    )

    assert result.current_trade_cycle is None
    assert recorder.calls[-2:] == [("save", True), ("journal", _STOP_RECORD)]


def test_bar_close_without_closure_writes_no_record() -> None:
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    _state_with_cycle(repository)
    resolver = _Resolver(
        position_open=True, first_fill_at_ms=1_200_000, average_entry_price="81660.6"
    )

    result = _orchestrator(recorder, repository, resolver, close=True).process(_unit())

    assert result.current_trade_cycle is None
    assert all(name != "journal" for name, _ in recorder.calls)


def _resolver_with_close(
    repository: InMemoryStrategyInstanceRuntimeStateRepository,
    recorder: _Recorder,
    confirmation: PositionClosedConfirmation,
) -> UncertainExchangeStateResolver:
    return UncertainExchangeStateResolver(
        state_repository=repository,
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        abi_entry_cycle_recovery=object(),  # type: ignore[arg-type]
        position_management_execution=_ClosePort(confirmation),  # type: ignore[arg-type]
        trade_cycle_closed_journal=_Journal(recorder),  # type: ignore[arg-type]
    )


def test_pending_close_cleared_by_a_stop_loss_closure_journals_with_null_bar() -> None:
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    _state_with_cycle(repository, pending_close=True)
    recorder.calls.clear()

    _resolver_with_close(
        repository, recorder, PositionClosedConfirmation(_SID, _CYCLE, _stop_closure())
    ).attempt(_SID)

    saved = repository.get(_SID)
    assert saved is not None
    assert saved.current_trade_cycle is None
    assert saved.pending_close_recovery is None
    assert recorder.calls == [
        ("save", True),
        ("journal", {**_STOP_RECORD, "bar_open_time_ms": None}),
    ]


def test_pending_close_without_closure_writes_no_record() -> None:
    recorder = _Recorder()
    repository = _RecordingRepository(recorder)
    _state_with_cycle(repository, pending_close=True)
    recorder.calls.clear()

    _resolver_with_close(repository, recorder, PositionClosedConfirmation(_SID, _CYCLE)).attempt(
        _SID
    )

    assert recorder.calls == [("save", True)]
