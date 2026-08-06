from dataclasses import replace
from typing import Literal

import pytest

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.engine.live_entry import LiveEntryProjectionResponse
from strategy_runtime.runtime.engine.open_trade import (
    OpenTradeProjectionRequest,
    OpenTradeProjectionResponse,
)
from strategy_runtime.runtime.entry_reconciliation import (
    EntryAbsentConfirmation,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator.orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.errors import (
    OpenPositionLookupProtocolError,
    OpenPositionLookupPublicError,
    OpenPositionLookupUnavailable,
)
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupResponse,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.resolver import OpenPositionResolver
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection
from strategy_runtime.runtime.routing.errors import (
    OpenTradeContextUnavailable,
    StrategyEngineProjectionUnavailable,
    StrategyInstanceBindingError,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.routing.router import StrategyUseCaseRouter
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


def state_request(
    *,
    strategy_instance_id: str = "ema_pullback:abc",
    strategy_id: str = "ema_pullback",
) -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=strategy_instance_id,
        strategy_id=strategy_id,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )


def runtime_state() -> StrategyInstanceRuntimeState:
    return InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(state_request())


def processing_unit(
    *,
    unit_instance_id: str = "ema_pullback:abc",
    deployment_instance_id: str = "ema_pullback:abc",
) -> StrategyBarProcessingUnit[DeploymentSpecification]:
    deployment = DeploymentSpecification(
        strategy_instance_id=deployment_instance_id,
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="ema_pullback",
        raw_spec={"ema": 200},
        source_path="/specs/a.json",
    )
    return StrategyBarProcessingUnit(
        strategy_instance_id=unit_instance_id,
        deployment=deployment,
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 1000),
    )


def desired_entry(side: Literal["long", "short"] = "long") -> DesiredEntry:
    return DesiredEntry(side, 900, "100.00", "99.00", "103.00", "runner")


DEFAULT_DESIRED_ENTRY = desired_entry()


class Abi:
    def __init__(
        self,
        response: OpenPositionLookupResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[object] = []

    def lookup(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class LiveEngine:
    def __init__(
        self,
        *,
        desired: DesiredEntry | None = DEFAULT_DESIRED_ENTRY,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[object] = []
        self.desired = desired
        self.error = error

    def project_live_entry(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LiveEntryProjectionResponse(desired_entry=self.desired)


class OpenEngine:
    def __init__(
        self,
        *,
        diagnostics=None,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[object] = []
        self.diagnostics = diagnostics or {"phase": "protected", "bars_in_trade": 3}
        self.error = error

    def project_open_trade(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return OpenTradeProjectionResponse(
            desired_protection=DesiredProtection("99.5", None),
            close_signal=CloseSignal(False),
            diagnostics=self.diagnostics,
        )


def resolved_state(
    *,
    position_open: bool,
    state: StrategyInstanceRuntimeState | None = None,
) -> PositionResolvedStrategyInstanceRuntimeState:
    target_state = state or frozen_trade_state() if position_open else (state or runtime_state())
    response = (
        OpenPositionLookupResponse(True, 950, "100.5")
        if position_open
        else OpenPositionLookupResponse(False)
    )
    return OpenPositionResolver(Abi(response)).resolve(target_state)


def frozen_trade_state() -> StrategyInstanceRuntimeState:
    state = runtime_state()
    return replace(
        state,
        current_trade_cycle=CurrentTradeCycle(
            "cycle-1",
            AppliedEntryPackage(
                applied_desired_entry=desired_entry(),
                calculated_quantity="0.1",
            ),
        ),
    )


def frozen_trade_state_with_context() -> StrategyInstanceRuntimeState:
    state = frozen_trade_state()
    cycle = state.current_trade_cycle
    assert cycle is not None
    frozen_context = FrozenExecutedEntryContext(
        desired_entry=cycle.applied_entry_package.applied_desired_entry,
        first_fill_at_ms=950,
        entry_bar_open_time_ms=900,
    )
    return replace(state, current_trade_cycle=replace(cycle, frozen_entry_context=frozen_context))


def router(
    *,
    live_engine: LiveEngine | None = None,
    open_engine: OpenEngine | None = None,
) -> StrategyUseCaseRouter:
    return StrategyUseCaseRouter(
        live_entry_engine=live_engine or LiveEngine(),
        open_trade_engine=open_engine or OpenEngine(),
    )


@pytest.mark.parametrize("invalid", [0, 1, "true", None])
def test_open_position_response_requires_an_exact_boolean(invalid) -> None:
    with pytest.raises(TypeError, match="position_open must be a boolean"):
        OpenPositionLookupResponse(invalid)


@pytest.mark.parametrize(
    ("position_open", "entry_time", "entry_price"),
    [
        (True, None, None),
        (True, 950, None),
        (True, None, "100.5"),
        (True, 0, "100.5"),
        (True, -1, "100.5"),
        (False, 950, None),
        (False, None, "100.5"),
        (False, 950, "100.5"),
    ],
)
def test_open_position_response_rejects_invalid_fact_combinations(
    position_open, entry_time, entry_price
) -> None:
    with pytest.raises(ValueError):
        OpenPositionLookupResponse(position_open, entry_time, entry_price)


def test_position_resolver_skips_abi_with_no_current_trade_cycle() -> None:
    state = runtime_state()
    assert state.current_trade_cycle is None
    abi = Abi(OpenPositionLookupResponse(True, 950, "100.5"))

    resolved = OpenPositionResolver(abi).resolve(state)

    assert abi.requests == []
    assert resolved.runtime_state is state
    assert resolved.position_open is False
    assert resolved.first_fill_at_ms is None
    assert resolved.average_entry_price is None


def test_position_resolver_calls_abi_with_existing_trade_cycle_id() -> None:
    state = frozen_trade_state()
    abi = Abi(OpenPositionLookupResponse(True, 950, "100.5000"))

    resolved = OpenPositionResolver(abi).resolve(state)

    assert len(abi.requests) == 1
    assert abi.requests[0].strategy_instance_id == state.strategy_instance_id
    assert abi.requests[0].trade_cycle_id == state.current_trade_cycle.trade_cycle_id
    assert resolved.runtime_state is state
    assert resolved.average_entry_price == "100.5"


@pytest.mark.parametrize(
    "error",
    [
        OpenPositionLookupUnavailable("timeout"),
        OpenPositionLookupProtocolError("malformed response"),
        OpenPositionLookupPublicError(
            status_code=422, code="unknown_trade_cycle_binding", message="no correlation record"
        ),
    ],
)
def test_position_resolver_propagates_typed_adapter_failures(error) -> None:
    with pytest.raises(type(error)) as raised:
        OpenPositionResolver(Abi(error=error)).resolve(frozen_trade_state())

    assert raised.value is error


def test_position_resolver_does_not_mask_programming_errors() -> None:
    error = AssertionError("adapter bug")
    with pytest.raises(AssertionError) as raised:
        OpenPositionResolver(Abi(error=error)).resolve(frozen_trade_state())

    assert raised.value is error


def test_router_projects_one_live_entry_without_mutating_state() -> None:
    state = runtime_state()
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=False, state=state),
    )
    expected = desired_entry("short")
    live_engine = LiveEngine(desired=expected)

    result = router(live_engine=live_engine).route(item)

    assert isinstance(result, LiveEntryProjectedStrategyInstance)
    assert result.source is item
    assert result.desired_entry is expected
    assert result.desired_entry.side == "short"
    assert len(live_engine.requests) == 1
    assert not hasattr(live_engine.requests[0], "instance_id")
    assert live_engine.requests[0].strategy_id == "ema_pullback"
    assert live_engine.requests[0].target_bar_open_time_ms == 1000
    assert state.current_trade_cycle is None


def test_router_preserves_no_desired_entry_without_side_arbitration() -> None:
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=False),
    )

    result = router(live_engine=LiveEngine(desired=None)).route(item)

    assert isinstance(result, LiveEntryProjectedStrategyInstance)
    assert result.desired_entry is None


def test_router_fails_closed_for_open_position_without_frozen_context() -> None:
    """Freezing the entry context is the orchestrator's job, not the router's.

    A router call bypassing that upstream freeze step must still fail
    closed rather than fabricate a request from unfrozen facts.
    """
    live_engine = LiveEngine()
    open_engine = OpenEngine()
    state = frozen_trade_state()
    assert state.current_trade_cycle is not None
    assert state.current_trade_cycle.frozen_entry_context is None
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=True, state=state),
    )

    with pytest.raises(OpenTradeContextUnavailable):
        router(live_engine=live_engine, open_engine=open_engine).route(item)

    assert live_engine.requests == []
    assert open_engine.requests == []


def test_router_routes_open_position_with_frozen_context() -> None:
    live_engine = LiveEngine()
    open_engine = OpenEngine()
    state = frozen_trade_state_with_context()
    assert state.current_trade_cycle is not None
    frozen_context = state.current_trade_cycle.frozen_entry_context
    assert frozen_context is not None
    mismatched_deployment = DeploymentSpecification(
        strategy_instance_id=state.strategy_instance_id,
        enabled=True,
        instrument="ETHUSDT.P",
        base_timeframe="1m",
        strategy_id="wrong_strategy",
        raw_spec={"different": True},
        source_path="/specs/other.json",
    )
    unit = StrategyBarProcessingUnit(
        strategy_instance_id=state.strategy_instance_id,
        deployment=mismatched_deployment,
        committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 1000),
    )
    item = PositionResolvedStrategyInstance(
        unit,
        resolved_state(position_open=True, state=state),
    )

    result = router(live_engine=live_engine, open_engine=open_engine).route(item)

    assert isinstance(result, OpenTradeProjectedStrategyInstance)
    assert result.source is item
    assert live_engine.requests == []
    assert len(open_engine.requests) == 1
    request = open_engine.requests[0]
    assert request.strategy_id == state.strategy_id
    assert request.raw_spec == state.registered_spec_snapshot.raw_spec
    assert request.ticker == state.registered_spec_snapshot.instrument
    assert request.base_timeframe == state.registered_spec_snapshot.base_timeframe
    assert request.target_bar_open_time_ms == 1000
    assert request.desired_entry is frozen_context.desired_entry
    assert request.entry_bar_open_time_ms == frozen_context.entry_bar_open_time_ms
    assert not hasattr(request, "average_entry_price")
    recipe = result.position_management_recipe
    assert recipe.desired_protection == DesiredProtection("99.5", None)
    assert recipe.close_signal == CloseSignal(False)
    assert dict(recipe.diagnostics) == {"phase": "protected", "bars_in_trade": 3}


def test_router_propagates_typed_engine_transport_failures_for_open_trade() -> None:
    error = StrategyEngineProjectionUnavailable("timeout")
    state = frozen_trade_state_with_context()
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=True, state=state),
    )
    target_router = router(open_engine=OpenEngine(error=error))

    with pytest.raises(StrategyEngineProjectionUnavailable) as raised:
        target_router.route(item)

    assert raised.value is error


def test_open_trade_request_contract_rejects_executed_entry_price() -> None:
    payload = {
        "strategy_id": "ema_pullback",
        "raw_spec": {"ema": 200},
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "target_bar_open_time_ms": 1000,
        "desired_entry": desired_entry(),
        "entry_bar_open_time_ms": 950,
        "executed_entry_price": "100.5",
    }

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        OpenTradeProjectionRequest(**payload)


@pytest.mark.parametrize(
    ("unit_instance_id", "deployment_instance_id", "state_instance_id"),
    [
        ("unit", "deployment", "unit"),
        ("unit", "unit", "state"),
    ],
)
def test_router_rejects_each_broken_strategy_instance_binding_link(
    unit_instance_id, deployment_instance_id, state_instance_id
) -> None:
    state = replace(runtime_state(), strategy_instance_id=state_instance_id)
    item = PositionResolvedStrategyInstance(
        processing_unit(
            unit_instance_id=unit_instance_id,
            deployment_instance_id=deployment_instance_id,
        ),
        resolved_state(position_open=False, state=state),
    )
    live_engine = LiveEngine()

    with pytest.raises(StrategyInstanceBindingError):
        router(live_engine=live_engine).route(item)

    assert live_engine.requests == []


def test_router_propagates_typed_engine_transport_failures() -> None:
    error = StrategyEngineProjectionUnavailable("timeout")
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=False),
    )
    target_router = router(live_engine=LiveEngine(error=error))

    with pytest.raises(StrategyEngineProjectionUnavailable) as raised:
        target_router.route(item)

    assert raised.value is error


def test_router_does_not_mask_engine_programming_errors() -> None:
    error = AssertionError("adapter bug")
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=False),
    )

    with pytest.raises(AssertionError) as raised:
        router(live_engine=LiveEngine(error=error)).route(item)

    assert raised.value is error


@pytest.mark.parametrize(
    "field",
    ["strategy_id", "instance_id", "ticker", "base_timeframe", "target_bar_open_time_ms"],
)
@pytest.mark.parametrize("branch", ["live", "open"])
def test_clean_engine_response_dtos_reject_obsolete_echo_fields(branch, field) -> None:
    if branch == "live":
        payload = {
            "desired_entry": desired_entry(),
            field: "obsolete",
        }
        response_type = LiveEntryProjectionResponse
    else:
        payload = {
            "desired_protection": DesiredProtection("99.5", None),
            "close_signal": CloseSignal(False),
            "diagnostics": {},
            field: "obsolete",
        }
        response_type = OpenTradeProjectionResponse

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        response_type(**payload)


def test_live_entry_response_rejects_old_side_wise_contract() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        LiveEntryProjectionResponse(  # type: ignore[call-arg]
            plans_by_side={"long": desired_entry(), "short": None}
        )


class CountingRepository:
    def __init__(self, state: StrategyInstanceRuntimeState) -> None:
        self.state = state
        self.requests: list[object] = []
        self.save_calls: list[StrategyInstanceRuntimeState] = []

    def get_or_create(self, request):
        self.requests.append(request)
        return self.state

    def get(self, strategy_instance_id):
        return self.state if strategy_instance_id == self.state.strategy_instance_id else None

    def save(self, state):
        self.save_calls.append(state)
        self.state = state
        return state


class CountingResolver:
    def __init__(self, resolved: PositionResolvedStrategyInstanceRuntimeState) -> None:
        self.resolved = resolved
        self.states: list[object] = []

    def resolve(self, state):
        self.states.append(state)
        return self.resolved


class CountingRouter:
    def __init__(self, projected: LiveEntryProjectedStrategyInstance) -> None:
        self.projected = projected
        self.items: list[object] = []

    def route(self, item):
        self.items.append(item)
        return self.projected


def test_semantic_orchestrator_calls_each_scalar_stage_once_and_applies_live_entry_projection() -> (
    None
):
    state = runtime_state()
    resolved = resolved_state(position_open=False, state=state)
    item = PositionResolvedStrategyInstance(processing_unit(), resolved)
    projected = LiveEntryProjectedStrategyInstance(item, None)
    repository = CountingRepository(state)
    resolver_port = CountingResolver(resolved)
    router_port = CountingRouter(projected)

    orchestrator = StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=resolver_port,
        use_case_router=router_port,
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        entry_reconciliation_orchestrator=EntryReconciliationOrchestrator(
            trade_cycle_id_factory=lambda: "trade-cycle-id",
            execution_port=type(
                "_NoOpExecutionPort",
                (),
                {
                    "execute": lambda self, command, source_state: EntryAbsentConfirmation(
                        strategy_instance_id=source_state.strategy_instance_id,
                        trade_cycle_id=command.trade_cycle_id,
                    ),
                },
            )(),
        ),
    )

    result = orchestrator.process(item.processing_unit)

    assert isinstance(result, StrategyInstanceRuntimeState)
    assert result.strategy_instance_id == state.strategy_instance_id
    assert result == state
    assert repository.save_calls == []
    assert len(repository.requests) == 1
    assert not hasattr(repository.requests[0], "risk_multiplier")
    assert "risk_multiplier" not in repository.requests[0].raw_spec
    assert state.risk_multiplier == "1"
    assert resolver_port.states == [state]
    assert len(router_port.items) == 1
    assert router_port.items[0].processing_unit is item.processing_unit
    assert router_port.items[0].resolved_state is resolved
    assert state.current_trade_cycle is None
