"""`open_trade_evaluated` and `protection_applied` journaling on the open-trade bar path
(runtime-open-trade-journal-v1): one `open_trade_evaluated` per successful Engine
open-trade answer, written before position management runs and carrying Engine's
own wire text; one `protection_applied` per ABI-confirmed protection, written
before the save; neither on a path that did not evaluate or confirm."""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import pytest

from strategy_runtime.infrastructure.strategy_engine.wire_codec import decode_open_trade_response
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.engine.live_entry import (
    LiveEntryProjectionRequest,
    LiveEntryProjectionResponse,
)
from strategy_runtime.runtime.engine.open_trade import (
    OpenTradeProjectionRequest,
    OpenTradeProjectionResponse,
)
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
    ProtectionOrder,
    ProtectionOrders,
)
from strategy_runtime.runtime.position_management_orchestrator import (
    PositionManagementOrchestrator,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.routing.models import LiveEntryProjectedStrategyInstance
from strategy_runtime.runtime.routing.router import StrategyUseCaseRouter
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingCloseRecovery,
    PendingEntryRecovery,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification
from strategy_runtime.utility.processing_journal import JsonlProcessingJournal

_SID = "ema_pullback:abc"
_CYCLE = "cycle-1"
_BAR = 1_800_000
_ENTRY_BAR = 1_200_000
_FIRST_FILL = 1_200_000

_INACTIVE_CLOSE = {"active": False, "reason": None, "component_id": None, "layer": None}
_ACTIVE_CLOSE = {
    "active": True,
    "reason": "strategy_exit",
    "component_id": "position_manager",
    "layer": "strategy",
}


def _engine_body(
    *,
    stop_price: str = "98",
    take_price: str | None = "103",
    close_signal: dict[str, object] | None = None,
) -> str:
    return json.dumps(
        {
            "desired_protection": {"stop_price": stop_price, "take_price": take_price},
            "close_signal": close_signal or _INACTIVE_CLOSE,
            "diagnostics": {"phase": "protected", "bars_in_trade": 3},
        }
    )


def _unit(bar_open_time_ms: int = _BAR) -> StrategyBarProcessingUnit[DeploymentSpecification]:
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


def _entry(side: Literal["long", "short"]) -> DesiredEntry:
    if side == "long":
        return DesiredEntry("long", 900, "100", "99", "103", "runner")
    return DesiredEntry("short", 900, "100", "101", "97", "runner")


@dataclass
class _Recorder:
    calls: list[tuple[str, object]] = field(default_factory=list)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def payload(self, name: str) -> dict[str, object]:
        (value,) = [value for call, value in self.calls if call == name]
        assert isinstance(value, dict)
        return value


class _Repository(InMemoryStrategyInstanceRuntimeStateRepository):
    def __init__(self, recorder: _Recorder, *, fail_save: bool = False) -> None:
        super().__init__()
        self._recorder = recorder
        self.fail_save = fail_save

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        if self.fail_save:
            raise RuntimeError("durable write failed")
        self._recorder.calls.append(("save", None))
        return super().save(state)


class _Journal:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def open_trade_evaluated(self, **fields: object) -> None:
        self._recorder.calls.append(("open_trade_evaluated", fields))

    def protection_applied(self, **fields: object) -> None:
        self._recorder.calls.append(("protection_applied", fields))


class _WireEngine:
    """Engine fake that answers through the real wire codec, from raw JSON text."""

    def __init__(
        self, recorder: _Recorder, body: str | None = None, error: Exception | None = None
    ) -> None:
        self._recorder = recorder
        self._body = body or _engine_body()
        self._error = error

    def project_open_trade(
        self, request: OpenTradeProjectionRequest
    ) -> OpenTradeProjectionResponse:
        self._recorder.calls.append(("engine", request.desired_entry.side))
        if self._error is not None:
            raise self._error
        return decode_open_trade_response(
            status_code=200, content_type="application/json", content=self._body.encode("utf-8")
        )

    def project_live_entry(
        self, request: LiveEntryProjectionRequest
    ) -> LiveEntryProjectionResponse:
        self._recorder.calls.append(("live_entry", None))
        return LiveEntryProjectionResponse(desired_entry=None)


_ORDERS = ProtectionOrders(
    quantity="0.010",
    stop=ProtectionOrder(order_id="stop-order-1", trigger_price="98.0"),
    take=ProtectionOrder(order_id="take-order-1", trigger_price="103.0"),
)


class _Port:
    def __init__(
        self,
        recorder: _Recorder,
        *,
        orders: ProtectionOrders = _ORDERS,
        error: Exception | None = None,
    ) -> None:
        self._recorder = recorder
        self._orders = orders
        self._error = error

    def apply_protection(self, command: ApplyProtectionCommand) -> ProtectionAppliedConfirmation:
        self._recorder.calls.append(("apply_protection", command))
        if self._error is not None:
            raise self._error
        return ProtectionAppliedConfirmation(
            command.strategy_instance_id,
            command.trade_cycle_id,
            command.desired_protection,
            self._orders,
        )

    def close_position(self, command: ClosePositionCommand) -> PositionClosedConfirmation:
        self._recorder.calls.append(("close_position", command))
        return PositionClosedConfirmation(command.strategy_instance_id, command.trade_cycle_id)


class _Resolver:
    def __init__(self, *, position_open: bool = True, closure: TradeCycleClosure | None = None):
        self._position_open = position_open
        self._closure = closure

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        if not self._position_open:
            return PositionResolvedStrategyInstanceRuntimeState(
                state, False, None, None, closure=self._closure
            )
        return PositionResolvedStrategyInstanceRuntimeState(
            state, True, _FIRST_FILL, "100", entry_order_link_id="abi-ep-link"
        )


class _Reconciliation:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def execute(
        self, projection: LiveEntryProjectedStrategyInstance
    ) -> StrategyInstanceRuntimeState:
        self._recorder.calls.append(("reconciliation", None))
        return projection.source.resolved_state.runtime_state


def _seed(
    repository: InMemoryStrategyInstanceRuntimeStateRepository,
    *,
    side: Literal["long", "short"] = "long",
    confirmed: DesiredProtection | None = None,
    entry_bar_open_time_ms: int = _ENTRY_BAR,
    **overrides: object,
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
    entry = _entry(side)
    cycle = CurrentTradeCycle(
        _CYCLE,
        AppliedEntryPackage(entry, "0.01"),
        FrozenExecutedEntryContext(entry, _FIRST_FILL, entry_bar_open_time_ms),
        confirmed,
    )
    return InMemoryStrategyInstanceRuntimeStateRepository.save(
        repository, replace(state, current_trade_cycle=cycle, **overrides)
    )


@dataclass
class _Harness:
    recorder: _Recorder
    repository: _Repository
    orchestrator: StrategyRuntimeOrchestrator


def _harness(
    *,
    body: str | None = None,
    engine_error: Exception | None = None,
    port_error: Exception | None = None,
    port_orders: ProtectionOrders = _ORDERS,
    resolver: _Resolver | None = None,
    journal: object | None = None,
    **seed: object,
) -> _Harness:
    recorder = _Recorder()
    repository = _Repository(recorder)
    _seed(repository, **seed)  # type: ignore[arg-type]
    engine = _WireEngine(recorder, body, engine_error)
    journal = journal or _Journal(recorder)
    orchestrator = StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=resolver or _Resolver(),  # type: ignore[arg-type]
        use_case_router=StrategyUseCaseRouter(live_entry_engine=engine, open_trade_engine=engine),
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=_Reconciliation(recorder),  # type: ignore[arg-type]
        position_management_orchestrator=PositionManagementOrchestrator(
            _Port(recorder, orders=port_orders, error=port_error),
            repository,
            protection_applied_journal=journal,  # type: ignore[arg-type]
        ),
        open_trade_journal=journal,  # type: ignore[arg-type]
    )
    return _Harness(recorder, repository, orchestrator)


def _jsonl(tmp_path: Path) -> JsonlProcessingJournal:
    return JsonlProcessingJournal(
        tmp_path / "journal" / "runtime.jsonl",
        event_id_factory=lambda: "event-1",
        timestamp_factory=lambda: "2026-10-19T00:00:00Z",
    )


def _records(journal: JsonlProcessingJournal) -> list[dict[str, object]]:
    return [json.loads(line) for line in journal.path.read_text().splitlines()]


# -- open_trade_evaluated: fidelity -------------------------------------------


def test_record_equals_engine_wire_answer_and_decision_uses_normalized_value(
    tmp_path: Path,
) -> None:
    close_signal = {
        "active": False,
        "reason": "trail_armed",
        "component_id": "trailing",
        "layer": "protective",
    }
    body = _engine_body(stop_price="105.150", take_price=None, close_signal=close_signal)
    journal = _jsonl(tmp_path)
    # Acknowledged protection equals the normalized answer: NoOp, no ABI call.
    harness = _harness(body=body, journal=journal, confirmed=DesiredProtection("105.15", None))

    harness.orchestrator.process(_unit())

    (record,) = _records(journal)
    wire = json.loads(body)
    assert record["event_type"] == "open_trade_evaluated"
    assert record["schema_version"] == 2
    assert record["strategy_instance_id"] == _SID
    assert record["diagnostics"] == {}
    assert record["payload"] == {
        "instrument": "BTCUSDT.P",
        "timeframe": "5m",
        "bar_open_time_ms": _BAR,
        "trade_cycle_id": _CYCLE,
        "side": "long",
        "desired_protection": wire["desired_protection"],
        "close_signal": wire["close_signal"],
    }
    assert record["payload"]["desired_protection"]["stop_price"] == "105.150"
    assert "apply_protection" not in harness.recorder.names()


def test_apply_command_carries_the_normalized_value_while_the_record_keeps_wire_text() -> None:
    harness = _harness(body=_engine_body(stop_price="98.50", take_price="103.000"))

    harness.orchestrator.process(_unit())

    evaluated = harness.recorder.payload("open_trade_evaluated")
    assert evaluated["desired_protection"] == {"stop_price": "98.50", "take_price": "103.000"}
    (command,) = [value for name, value in harness.recorder.calls if name == "apply_protection"]
    assert isinstance(command, ApplyProtectionCommand)
    assert command.desired_protection == DesiredProtection("98.5", "103")
    assert command.desired_protection.stop_price == "98.5"
    applied = harness.recorder.payload("protection_applied")
    assert applied["requested_protection"] == {"stop_price": "98.5", "take_price": "103"}


# -- the three decisions -------------------------------------------------------


def test_noop_bar_writes_one_open_trade_evaluated_and_no_protection_applied() -> None:
    harness = _harness(body=_engine_body(stop_price="99", take_price="103"))

    harness.orchestrator.process(_unit())

    assert harness.recorder.names() == ["engine", "open_trade_evaluated"]
    assert harness.recorder.payload("open_trade_evaluated") == {
        "strategy_instance_id": _SID,
        "instrument": "BTCUSDT.P",
        "timeframe": "5m",
        "bar_open_time_ms": _BAR,
        "trade_cycle_id": _CYCLE,
        "side": "long",
        "desired_protection": {"stop_price": "99", "take_price": "103"},
        "close_signal": _INACTIVE_CLOSE,
    }


def test_apply_protection_journals_evaluation_then_confirmation_before_the_save() -> None:
    harness = _harness(body=_engine_body(stop_price="98", take_price="103"))

    state = harness.orchestrator.process(_unit())

    assert harness.recorder.names() == [
        "engine",
        "open_trade_evaluated",
        "apply_protection",
        "protection_applied",
        "save",
    ]
    assert harness.recorder.payload("protection_applied") == {
        "strategy_instance_id": _SID,
        "trade_cycle_id": _CYCLE,
        "bar_open_time_ms": _BAR,
        "requested_protection": {"stop_price": "98", "take_price": "103"},
        "confirmed_protection": {"stop_price": "98", "take_price": "103"},
        "position_quantity": "0.010",
        "stop_order": {"order_id": "stop-order-1", "trigger_price": "98.0"},
        "take_order": {"order_id": "take-order-1", "trigger_price": "103.0"},
    }
    assert state.current_trade_cycle is not None
    assert state.current_trade_cycle.latest_confirmed_management_protection == (
        DesiredProtection("98", "103")
    )


def test_close_position_journals_the_active_close_signal_and_no_protection_applied() -> None:
    harness = _harness(body=_engine_body(close_signal=_ACTIVE_CLOSE))

    harness.orchestrator.process(_unit())

    names = harness.recorder.names()
    assert names[:3] == ["engine", "open_trade_evaluated", "save"]  # pending-close pre-write
    assert "close_position" in names
    assert names.index("open_trade_evaluated") < names.index("close_position")
    assert "protection_applied" not in names
    assert harness.recorder.payload("open_trade_evaluated")["close_signal"] == _ACTIVE_CLOSE


def test_short_position_with_no_take_is_journaled_with_null_take_and_real_take_order(
    tmp_path: Path,
) -> None:
    journal = _jsonl(tmp_path)
    surrogate = ProtectionOrders(
        quantity="0.010",
        stop=ProtectionOrder(order_id="stop-order-1", trigger_price="100.5"),
        take=ProtectionOrder(order_id="take-order-1", trigger_price="0.1"),
    )
    harness = _harness(
        body=_engine_body(stop_price="100.5", take_price=None),
        journal=journal,
        port_orders=surrogate,
        side="short",
    )

    harness.orchestrator.process(_unit())

    evaluated, applied = _records(journal)
    assert evaluated["event_type"] == "open_trade_evaluated"
    assert evaluated["payload"]["side"] == "short"
    assert evaluated["payload"]["desired_protection"] == {"stop_price": "100.5", "take_price": None}
    assert applied["event_type"] == "protection_applied"
    assert applied["payload"]["requested_protection"] == {"stop_price": "100.5", "take_price": None}
    assert applied["payload"]["confirmed_protection"] == {"stop_price": "100.5", "take_price": None}
    assert applied["payload"]["take_order"] == {"order_id": "take-order-1", "trigger_price": "0.1"}
    assert applied["diagnostics"] == {}


# -- paths that evaluate or confirm nothing ----------------------------------


@pytest.mark.parametrize(
    ("seed", "bar_open_time_ms"),
    [
        ({"pending_entry_recovery": PendingEntryRecovery(_CYCLE)}, _BAR),
        ({"pending_close_recovery": PendingCloseRecovery(_CYCLE)}, _BAR),
        ({}, _ENTRY_BAR - 300_000),
    ],
    ids=["pending_entry_recovery", "pending_close_recovery", "entry_bar_after_committed_bar"],
)
def test_no_record_when_the_bar_is_skipped(seed: dict[str, object], bar_open_time_ms: int) -> None:
    harness = _harness(**seed)

    harness.orchestrator.process(_unit(bar_open_time_ms))

    assert "engine" not in harness.recorder.names()
    assert "open_trade_evaluated" not in harness.recorder.names()


def test_no_record_when_a_closure_is_detected_on_resolve() -> None:
    closure = TradeCycleClosure(_SID, _CYCLE, "stop_loss", "a34add42", None, "abi-ep-1")
    harness = _harness(resolver=_Resolver(position_open=False, closure=closure))

    harness.orchestrator.process(_unit())

    assert harness.recorder.names() == ["save"]


def test_no_record_when_routed_to_live_entry() -> None:
    harness = _harness(resolver=_Resolver(position_open=False))

    harness.orchestrator.process(_unit())

    assert harness.recorder.names() == ["live_entry", "reconciliation"]


def test_no_record_when_engine_open_trade_fails() -> None:
    harness = _harness(engine_error=RuntimeError("engine down"))

    with pytest.raises(RuntimeError, match="engine down"):
        harness.orchestrator.process(_unit())

    assert harness.recorder.names() == ["engine"]


def test_abi_failure_keeps_open_trade_evaluated_and_writes_no_protection_applied() -> None:
    harness = _harness(port_error=RuntimeError("abi down"))

    with pytest.raises(RuntimeError, match="abi down"):
        harness.orchestrator.process(_unit())

    assert harness.recorder.names() == ["engine", "open_trade_evaluated", "apply_protection"]


def test_save_failure_after_confirmation_keeps_the_record_and_a_repeat_writes_another() -> None:
    harness = _harness()
    harness.repository.fail_save = True

    with pytest.raises(RuntimeError, match="durable write failed"):
        harness.orchestrator.process(_unit())
    harness.repository.fail_save = False
    harness.orchestrator.process(_unit(_BAR + 300_000))

    assert harness.recorder.names().count("protection_applied") == 2
    assert harness.recorder.names()[-1] == "save"


# -- best effort ---------------------------------------------------------------


def test_unwritable_journal_does_not_change_the_bar_outcome(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    journal = JsonlProcessingJournal(
        blocked,
        event_id_factory=lambda: "event-1",
        timestamp_factory=lambda: "2026-10-19T00:00:00Z",
    )
    with_journal = _harness(journal=journal)
    without_journal = _harness()

    state = with_journal.orchestrator.process(_unit())
    expected = without_journal.orchestrator.process(_unit())

    assert journal.failure_count == 2
    assert state == expected
    assert with_journal.repository.get(_SID) == expected
    assert state.current_trade_cycle is not None
    assert state.current_trade_cycle.latest_confirmed_management_protection == (
        DesiredProtection("98", "103")
    )
