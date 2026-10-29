"""Entry-remainder cancel step in `StrategyRuntimeOrchestrator.process(...)`
(runtime-touch-trigger-remainder-cancel-v1): one ABI call once the frozen boundary is
reached, the mark saved on a confirmed answer, and position management never stopped."""

from dataclasses import dataclass, field, replace

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionProtocolError,
    PositionManagementExecutionPublicError,
    PositionManagementExecutionTimeout,
    PositionManagementExecutionUnavailable,
)
from strategy_runtime.runtime.position_management_execution.models import (
    EntryRemainderCancelConfirmation,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.routing.models import (
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingCloseRecovery,
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
_CYCLE = "cycle-1"
_M5 = 300_000
_T0 = 1_785_000_000_000  # signal bar 12:00
_BOUNDARY = _T0 + 5 * _M5  # N = 3: the order ends on the bar that closes at 12:25
_ENTRY = DesiredEntry("long", _T0, "100", "99", "103", "runner")


@dataclass
class _Recorder:
    calls: list[tuple[str, object]] = field(default_factory=list)


class _Resolver:
    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        return PositionResolvedStrategyInstanceRuntimeState(
            state, True, _T0 + 1_000, "100", entry_order_link_id="link-1"
        )


class _Router:
    def route(self, item: PositionResolvedStrategyInstance) -> OpenTradeProjectedStrategyInstance:
        return OpenTradeProjectedStrategyInstance(item, None)  # type: ignore[arg-type]


class _PositionManagement:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def execute_with_closure(
        self, projection: OpenTradeProjectedStrategyInstance
    ) -> tuple[StrategyInstanceRuntimeState, None]:
        state = projection.source.resolved_state.runtime_state
        cycle = state.current_trade_cycle
        assert cycle is not None
        self._recorder.calls.append(("manage", cycle.entry_remainder_cancelled))
        return state, None


class _Abi:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder
        self.failures: list[Exception] = []
        self.status = "entry_remainder_cancelled"

    def cancel_entry_remainder(
        self, strategy_instance_id: str, trade_cycle_id: str
    ) -> EntryRemainderCancelConfirmation:
        self._recorder.calls.append(("abi", (strategy_instance_id, trade_cycle_id)))
        if self.failures:
            raise self.failures.pop(0)
        return EntryRemainderCancelConfirmation(
            strategy_instance_id, trade_cycle_id, self.status, "0.004"
        )


class _Journal:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def entry_remainder_cancelled(self, **fields: object) -> None:
        self._recorder.calls.append(("cancelled", fields))

    def entry_remainder_cancel_failed(self, **fields: object) -> None:
        self._recorder.calls.append(("failed", fields))


@dataclass
class _Harness:
    recorder: _Recorder
    repository: InMemoryStrategyInstanceRuntimeStateRepository
    abi: _Abi
    lifetime: int | None

    def orchestrator(self) -> StrategyRuntimeOrchestrator:
        return StrategyRuntimeOrchestrator(
            state_repository=self.repository,
            open_position_resolver=_Resolver(),  # type: ignore[arg-type]
            use_case_router=_Router(),  # type: ignore[arg-type]
            keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
            entry_reconciliation_orchestrator=None,  # type: ignore[arg-type]
            position_management_orchestrator=_PositionManagement(self.recorder),  # type: ignore[arg-type]
            entry_order_lifetime_bars=self.lifetime,
            entry_remainder_cancel_port=self.abi,
            entry_remainder_cancel_journal=_Journal(self.recorder),
        )

    def bar(self, open_time_ms: int) -> list[tuple[str, object]]:
        self.recorder.calls.clear()
        self.orchestrator().process(_unit(open_time_ms))
        return list(self.recorder.calls)

    def cycle(self) -> CurrentTradeCycle:
        state = self.repository.get(_SID)
        assert state is not None and state.current_trade_cycle is not None
        return state.current_trade_cycle


def _harness(*, frozen: bool, lifetime: int | None = 3) -> _Harness:
    recorder = _Recorder()
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
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
    context = (
        FrozenExecutedEntryContext(
            _ENTRY,
            _T0 + 1_000,
            _T0,
            entry_order_expires_at_bar=None if lifetime is None else _BOUNDARY,
        )
        if frozen
        else None
    )
    repository.save(
        replace(
            state,
            current_trade_cycle=CurrentTradeCycle(
                _CYCLE, AppliedEntryPackage(_ENTRY, "0.010"), context
            ),
        )
    )
    return _Harness(recorder, repository, _Abi(recorder), lifetime)


def _unit(open_time_ms: int) -> StrategyBarProcessingUnit[DeploymentSpecification]:
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
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", open_time_ms),
    )


def _cancelled(bar: int, status: str = "entry_remainder_cancelled") -> tuple[str, object]:
    return (
        "cancelled",
        {
            "strategy_instance_id": _SID,
            "trade_cycle_id": _CYCLE,
            "bar_open_time_ms": bar,
            "status": status,
            "executed_quantity": "0.004",
        },
    )


def _failed(bar: int, error: str) -> tuple[str, object]:
    return (
        "failed",
        {
            "strategy_instance_id": _SID,
            "trade_cycle_id": _CYCLE,
            "bar_open_time_ms": bar,
            "error": error,
        },
    )


def test_first_fill_in_touch_trigger_freezes_the_boundary_from_the_signal_bar() -> None:
    harness = _harness(frozen=False)

    harness.bar(_T0)

    context = harness.cycle().frozen_entry_context
    assert context is not None
    assert context.entry_order_expires_at_bar == _BOUNDARY


def test_no_call_before_the_boundary_bar() -> None:
    harness = _harness(frozen=True)

    for bar in (_T0, _T0 + _M5, _T0 + 2 * _M5, _T0 + 3 * _M5):  # 12:00 .. 12:15
        assert harness.bar(bar) == [("manage", False)]


def test_one_call_on_the_boundary_bar_sets_the_mark_before_management() -> None:
    harness = _harness(frozen=True)
    bar = _T0 + 4 * _M5  # 12:20, closes 12:25

    calls = harness.bar(bar)

    assert calls == [("abi", (_SID, _CYCLE)), _cancelled(bar), ("manage", True)]
    assert harness.cycle().entry_remainder_cancelled is True


def test_already_terminal_answer_also_sets_the_mark() -> None:
    harness = _harness(frozen=True)
    harness.abi.status = "entry_order_already_terminal"
    bar = _T0 + 4 * _M5

    calls = harness.bar(bar)

    assert calls[1] == _cancelled(bar, "entry_order_already_terminal")
    assert harness.cycle().entry_remainder_cancelled is True


def test_no_call_after_the_mark_also_after_a_restart() -> None:
    harness = _harness(frozen=True)
    harness.bar(_T0 + 4 * _M5)

    # A fresh orchestrator over the same durable state stands for a restart.
    assert harness.bar(_T0 + 5 * _M5) == [("manage", True)]
    assert harness.bar(_T0 + 9 * _M5) == [("manage", True)]


def test_a_late_first_fill_calls_on_the_same_bar() -> None:
    harness = _harness(frozen=False)
    bar = _T0 + 6 * _M5  # first observed after the boundary

    calls = harness.bar(bar)

    assert calls == [("abi", (_SID, _CYCLE)), _cancelled(bar), ("manage", True)]


def test_ema_anchor_never_calls() -> None:
    harness = _harness(frozen=False, lifetime=None)

    for bar in (_T0, _T0 + 4 * _M5, _T0 + 20 * _M5):
        assert harness.bar(bar) == [("manage", False)]
    context = harness.cycle().frozen_entry_context
    assert context is not None and context.entry_order_expires_at_bar is None


def test_failures_keep_managing_and_retry_on_the_next_bar() -> None:
    harness = _harness(frozen=True)
    harness.abi.failures = [
        PositionManagementExecutionTimeout("timed out"),
        PositionManagementExecutionPublicError(
            status_code=422, code="entry_not_filled", message="no fill"
        ),
        PositionManagementExecutionUnavailable("HTTP 500"),
        PositionManagementExecutionProtocolError("bad body"),
    ]
    errors = [
        "PositionManagementExecutionTimeout",
        "PositionManagementExecutionPublicError",
        "PositionManagementExecutionUnavailable",
        "PositionManagementExecutionProtocolError",
    ]

    for index, error in enumerate(errors):
        bar = _T0 + (4 + index) * _M5
        assert harness.bar(bar) == [
            ("abi", (_SID, _CYCLE)),
            _failed(bar, error),
            ("manage", False),
        ]
        assert harness.cycle().entry_remainder_cancelled is False

    bar = _T0 + 8 * _M5
    assert harness.bar(bar) == [("abi", (_SID, _CYCLE)), _cancelled(bar), ("manage", True)]


def test_a_pending_recovery_marker_returns_before_the_step() -> None:
    harness = _harness(frozen=True)
    state = harness.repository.get(_SID)
    assert state is not None
    harness.repository.save(replace(state, pending_close_recovery=PendingCloseRecovery(_CYCLE)))

    assert harness.bar(_T0 + 4 * _M5) == []
