from dataclasses import replace

import pytest

from strategy_runtime.runtime.engine.live_entry import LiveEntryProjectionResponse
from strategy_runtime.runtime.engine.open_trade import (
    OpenTradeProjectionRequest,
    OpenTradeProjectionResponse,
)
from strategy_runtime.runtime.open_position.errors import (
    OpenPositionLookupProtocolError,
    OpenPositionLookupUnavailable,
)
from strategy_runtime.runtime.open_position.models import (
    OpenPositionLookupResponse,
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.resolver import OpenPositionResolver
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import EntryRecipe, LiveEntryPlan
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
    CurrentTradeCycle,
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


def plan(side: str) -> LiveEntryPlan:
    return LiveEntryPlan(side, 900, "100.00", "99.00", "103.00", "runner")


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
        error: Exception | None = None,
    ) -> None:
        self.requests: list[object] = []
        self.error = error

    def project_live_entry(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LiveEntryProjectionResponse(
            plans_by_side={
                "long": plan("long"),
                "short": None,
            }
        )


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
    target_state = state or runtime_state()
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
            EntryRecipe(plan("long"), None),
            True,
        ),
    )


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


def test_position_resolver_is_scalar_and_sends_identity_only() -> None:
    state = runtime_state()
    abi = Abi(OpenPositionLookupResponse(True, 950, "100.5000"))

    resolved = OpenPositionResolver(abi).resolve(state)

    assert len(abi.requests) == 1
    assert abi.requests[0].strategy_instance_id == state.strategy_instance_id
    assert resolved.runtime_state is state
    assert resolved.executed_entry_price == "100.5"


@pytest.mark.parametrize(
    "error",
    [
        OpenPositionLookupUnavailable("timeout"),
        OpenPositionLookupProtocolError("malformed response"),
    ],
)
def test_position_resolver_propagates_typed_adapter_failures(error) -> None:
    with pytest.raises(type(error)) as raised:
        OpenPositionResolver(Abi(error=error)).resolve(runtime_state())

    assert raised.value is error


def test_position_resolver_does_not_mask_programming_errors() -> None:
    error = AssertionError("adapter bug")
    with pytest.raises(AssertionError) as raised:
        OpenPositionResolver(Abi(error=error)).resolve(runtime_state())

    assert raised.value is error


def test_router_projects_one_live_entry_without_mutating_state() -> None:
    state = runtime_state()
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=False, state=state),
    )
    live_engine = LiveEngine()

    result = router(live_engine=live_engine).route(item)

    assert isinstance(result, LiveEntryProjectedStrategyInstance)
    assert result.source is item
    assert result.entry_recipe.long_plan == plan("long")
    assert result.entry_recipe.short_plan is None
    assert len(live_engine.requests) == 1
    assert not hasattr(live_engine.requests[0], "instance_id")
    assert live_engine.requests[0].strategy_id == "ema_pullback"
    assert live_engine.requests[0].target_bar_open_time_ms == 1000
    assert state.current_trade_cycle is None


def test_router_projects_one_open_trade_from_frozen_entry_context() -> None:
    state = frozen_trade_state()
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=True, state=state),
    )
    open_engine = OpenEngine()

    result = router(open_engine=open_engine).route(item)

    assert isinstance(result, OpenTradeProjectedStrategyInstance)
    assert result.source is item
    assert len(open_engine.requests) == 1
    assert not hasattr(open_engine.requests[0], "instance_id")
    assert open_engine.requests[0].strategy_id == "ema_pullback"
    assert open_engine.requests[0].target_bar_open_time_ms == 1000
    assert open_engine.requests[0].entry_recipe == state.current_trade_cycle.entry_recipe
    assert not hasattr(open_engine.requests[0], "executed_entry_price")
    assert state.current_trade_cycle.position_management_recipe is None


def test_open_trade_request_contract_rejects_executed_entry_price() -> None:
    payload = {
        "strategy_id": "ema_pullback",
        "raw_spec": {"ema": 200},
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "target_bar_open_time_ms": 1000,
        "entry_recipe": EntryRecipe(plan("long"), None),
        "entry_bar_open_time_ms": 950,
        "executed_entry_price": "100.5",
    }

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        OpenTradeProjectionRequest(**payload)


def test_router_does_not_call_engine_when_open_trade_context_is_missing() -> None:
    live_engine = LiveEngine()
    open_engine = OpenEngine()
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=True),
    )

    with pytest.raises(OpenTradeContextUnavailable):
        router(live_engine=live_engine, open_engine=open_engine).route(item)

    assert live_engine.requests == []
    assert open_engine.requests == []


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


@pytest.mark.parametrize("branch", ["live", "open"])
def test_router_propagates_typed_engine_transport_failures(branch) -> None:
    error = StrategyEngineProjectionUnavailable("timeout")
    if branch == "live":
        item = PositionResolvedStrategyInstance(
            processing_unit(),
            resolved_state(position_open=False),
        )
        target_router = router(live_engine=LiveEngine(error=error))
    else:
        item = PositionResolvedStrategyInstance(
            processing_unit(),
            resolved_state(position_open=True, state=frozen_trade_state()),
        )
        target_router = router(open_engine=OpenEngine(error=error))

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
            "plans_by_side": {"long": plan("long"), "short": None},
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


def test_open_trade_diagnostics_are_opaque_and_recursively_immutable() -> None:
    diagnostics = {
        "arbitrary": {"nested": [1, {"flag": True}]},
        "vendor_extension": None,
    }
    item = PositionResolvedStrategyInstance(
        processing_unit(),
        resolved_state(position_open=True, state=frozen_trade_state()),
    )

    result = router(open_engine=OpenEngine(diagnostics=diagnostics)).route(item)

    assert isinstance(result, OpenTradeProjectedStrategyInstance)
    frozen = result.position_management_recipe.diagnostics
    assert frozen["arbitrary"]["nested"][1]["flag"] is True
    diagnostics["arbitrary"]["nested"][1]["flag"] = False
    assert frozen["arbitrary"]["nested"][1]["flag"] is True
    with pytest.raises(TypeError):
        frozen["another"] = "value"


class CountingRepository:
    def __init__(self, state: StrategyInstanceRuntimeState) -> None:
        self.state = state
        self.requests: list[object] = []

    def get_or_create(self, request):
        self.requests.append(request)
        return self.state


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


def test_semantic_orchestrator_calls_each_scalar_stage_once_and_stops_at_projection() -> None:
    state = runtime_state()
    resolved = resolved_state(position_open=False, state=state)
    item = PositionResolvedStrategyInstance(processing_unit(), resolved)
    projected = LiveEntryProjectedStrategyInstance(item, EntryRecipe(plan("long"), None))
    repository = CountingRepository(state)
    resolver_port = CountingResolver(resolved)
    router_port = CountingRouter(projected)
    orchestrator = StrategyRuntimeOrchestrator(
        state_repository=repository,
        open_position_resolver=resolver_port,
        use_case_router=router_port,
    )

    result = orchestrator.process(item.processing_unit)

    assert result is projected
    assert len(repository.requests) == 1
    assert resolver_port.states == [state]
    assert len(router_port.items) == 1
    assert router_port.items[0].processing_unit is item.processing_unit
    assert router_port.items[0].resolved_state is resolved
    assert state.current_trade_cycle is None
