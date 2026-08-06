from dataclasses import replace
from inspect import signature
from typing import Literal, cast

import pytest

from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.position_management_decision.errors import (
    PositionManagementDecisionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.position_management_orchestrator.orchestrator import (
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
    FrozenExecutedEntryContext,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    StrategyBarProcessingUnit,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification


def desired_entry(
    *,
    side: Literal["long", "short"] = "long",
    initial_stop_price: str = "99",
    initial_take_price: str = "103",
) -> DesiredEntry:
    return DesiredEntry(side, 900, "100", initial_stop_price, initial_take_price, "runner")


def runtime_state(
    *,
    latest_confirmed_management_protection: DesiredProtection | None = None,
) -> StrategyInstanceRuntimeState:
    entry = desired_entry()
    return StrategyInstanceRuntimeState(
        strategy_instance_id="instance",
        strategy_id="strategy",
        registered_spec_snapshot=RegisteredSpecSnapshot(
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={},
            source_path="a.json",
        ),
        risk_multiplier="1",
        current_trade_cycle=CurrentTradeCycle(
            "cycle-1",
            AppliedEntryPackage(entry, "0.01"),
            FrozenExecutedEntryContext(entry, first_fill_at_ms=950, entry_bar_open_time_ms=900),
            latest_confirmed_management_protection,
        ),
    )


def recipe(
    *,
    stop_price: str = "99",
    take_price: str | None = "103",
    active: bool = False,
) -> PositionManagementRecipe:
    return PositionManagementRecipe(
        desired_protection=DesiredProtection(stop_price, take_price),
        close_signal=CloseSignal(active),
        diagnostics={},
    )


def projection(
    source_state: StrategyInstanceRuntimeState,
    position_management_recipe: PositionManagementRecipe,
) -> OpenTradeProjectedStrategyInstance:
    deployment = DeploymentSpecification(
        strategy_instance_id="instance",
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        strategy_id="strategy",
        raw_spec={},
        source_path="a.json",
    )
    source = PositionResolvedStrategyInstance(
        processing_unit=StrategyBarProcessingUnit(
            strategy_instance_id="instance",
            deployment=deployment,
            committed_bar=CommittedBarEvent("BTCUSDT.P", "5m", 1000),
        ),
        resolved_state=PositionResolvedStrategyInstanceRuntimeState(
            runtime_state=source_state,
            position_open=True,
            first_fill_at_ms=950,
            average_entry_price="100",
        ),
    )
    return OpenTradeProjectedStrategyInstance(source, position_management_recipe)


class FakeExecutionPort:
    def __init__(
        self,
        *,
        apply_result: ProtectionAppliedConfirmation | object | None = None,
        close_result: PositionClosedConfirmation | object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.apply_result = apply_result
        self.close_result = close_result
        self.error = error
        self.apply_calls: list[ApplyProtectionCommand] = []
        self.close_calls: list[ClosePositionCommand] = []

    def apply_protection(
        self,
        command: ApplyProtectionCommand,
    ) -> ProtectionAppliedConfirmation:
        self.apply_calls.append(command)
        if self.error is not None:
            raise self.error
        return cast("ProtectionAppliedConfirmation", self.apply_result)

    def close_position(
        self,
        command: ClosePositionCommand,
    ) -> PositionClosedConfirmation:
        self.close_calls.append(command)
        if self.error is not None:
            raise self.error
        return cast("PositionClosedConfirmation", self.close_result)


def test_no_op_calls_neither_port_method_and_returns_source_state_unchanged() -> None:
    source_state = runtime_state()
    snapshot = replace(source_state)
    item = projection(source_state, recipe(stop_price="99", take_price="103"))
    port = FakeExecutionPort()

    result = PositionManagementOrchestrator(port).execute(item)

    assert result == snapshot
    assert source_state == snapshot
    assert port.apply_calls == []
    assert port.close_calls == []


def test_apply_protection_calls_only_apply_protection_exactly_once() -> None:
    source_state = runtime_state()
    snapshot = replace(source_state)
    protection = DesiredProtection("98", "103")
    item = projection(source_state, recipe(stop_price="98", take_price="103"))
    confirmation = ProtectionAppliedConfirmation("instance", "cycle-1", protection)
    port = FakeExecutionPort(apply_result=confirmation)

    result = PositionManagementOrchestrator(port).execute(item)

    assert len(port.apply_calls) == 1
    assert port.apply_calls[0] == ApplyProtectionCommand("instance", "cycle-1", protection)
    assert port.close_calls == []
    assert source_state == snapshot
    assert result.current_trade_cycle == replace(
        snapshot.current_trade_cycle,  # type: ignore[union-attr]
        latest_confirmed_management_protection=protection,
    )


def test_close_position_calls_only_close_position_exactly_once() -> None:
    source_state = runtime_state()
    snapshot = replace(source_state)
    item = projection(source_state, recipe(active=True))
    confirmation = PositionClosedConfirmation("instance", "cycle-1")
    port = FakeExecutionPort(close_result=confirmation)

    result = PositionManagementOrchestrator(port).execute(item)

    assert port.apply_calls == []
    assert len(port.close_calls) == 1
    assert port.close_calls[0] == ClosePositionCommand("instance", "cycle-1")
    assert source_state == snapshot
    assert result.current_trade_cycle is None


def test_port_failure_propagates_and_yields_no_new_state() -> None:
    source_state = runtime_state()
    snapshot = replace(source_state)
    item = projection(source_state, recipe(active=True))
    error = RuntimeError("executor unreachable")
    port = FakeExecutionPort(error=error)

    with pytest.raises(RuntimeError) as raised:
        PositionManagementOrchestrator(port).execute(item)

    assert raised.value is error
    assert len(port.close_calls) == 1
    assert source_state == snapshot


def test_mismatched_confirmation_raises_and_yields_no_new_state() -> None:
    source_state = runtime_state()
    snapshot = replace(source_state)
    item = projection(source_state, recipe(stop_price="98", take_price="103"))
    port = FakeExecutionPort(apply_result=PositionClosedConfirmation("instance", "cycle-1"))

    with pytest.raises(PositionManagementExecutionInvariantError):
        PositionManagementOrchestrator(port).execute(item)

    assert source_state == snapshot


def test_decision_invariant_failure_propagates_before_any_port_call() -> None:
    source_state = replace(runtime_state(), current_trade_cycle=None)
    snapshot = replace(source_state)
    item = projection(source_state, recipe())
    port = FakeExecutionPort()

    with pytest.raises(PositionManagementDecisionInvariantError):
        PositionManagementOrchestrator(port).execute(item)

    assert port.apply_calls == []
    assert port.close_calls == []
    assert source_state == snapshot


def test_execute_signature_takes_only_the_projection() -> None:
    assert tuple(signature(PositionManagementOrchestrator.execute).parameters) == (
        "self",
        "projection",
    )
