from dataclasses import fields, replace
from inspect import signature
from typing import cast
from unittest.mock import patch

import pytest

from strategy_runtime.runtime.entry_reconciliation import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    EntryReconciliationInvariantError,
    SuccessfulEntryConfirmation,
    apply_success_confirmation,
    build_entry_reconciliation_command,
    decide_entry_reconciliation,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
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

ORCHESTRATOR_MODULE = "strategy_runtime.runtime.entry_reconciliation_orchestrator.orchestrator"


def desired_entry(*, price: str = "100", side: str = "long") -> DesiredEntry:
    return DesiredEntry(
        cast("str", side),
        900,
        price,
        "99",
        "103",
        "runner",
    )


def seeded_repository(
    *,
    applied_entry: DesiredEntry | None = None,
) -> tuple[InMemoryStrategyInstanceRuntimeStateRepository, StrategyInstanceRuntimeState]:
    """Register one instance in a fresh in-memory repository, optionally with a current cycle."""
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    state = repository.get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id="instance",
            strategy_id="strategy",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={},
            source_path="a.json",
        )
    )
    if applied_entry is None:
        return repository, state
    state = repository.save(
        replace(
            state,
            current_trade_cycle=CurrentTradeCycle(
                "cycle-1",
                AppliedEntryPackage(applied_entry, "0.01"),
            ),
        )
    )
    return repository, state


def projection(
    source_state: StrategyInstanceRuntimeState,
    new_desired_entry: DesiredEntry | None,
) -> LiveEntryProjectedStrategyInstance:
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
            position_open=False,
            first_fill_at_ms=None,
            average_entry_price=None,
        ),
    )
    return LiveEntryProjectedStrategyInstance(source, new_desired_entry)


class RecordingIdFactory:
    def __init__(
        self,
        result: str = "cycle-new",
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class FakeExecutionPort:
    def __init__(
        self,
        result: SuccessfulEntryConfirmation | object,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[EntryReconciliationCommand, StrategyInstanceRuntimeState]] = []

    def execute(
        self,
        command: EntryReconciliationCommand,
        source_state: StrategyInstanceRuntimeState,
    ) -> SuccessfulEntryConfirmation:
        self.calls.append((command, source_state))
        if self.error is not None:
            raise self.error
        return cast("SuccessfulEntryConfirmation", self.result)


@pytest.mark.parametrize(
    ("acknowledged", "projected"),
    [
        (None, None),
        (desired_entry(), desired_entry()),
    ],
)
def test_both_no_op_cases_preserve_source_value_and_bypass_command_work(
    acknowledged: DesiredEntry | None,
    projected: DesiredEntry | None,
) -> None:
    repository, source_state = seeded_repository(applied_entry=acknowledged)
    snapshot = replace(source_state)
    item = projection(source_state, projected)
    id_factory = RecordingIdFactory()
    execution_port = FakeExecutionPort(object())

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.decide_entry_reconciliation",
            wraps=decide_entry_reconciliation,
        ) as decide,
        patch(
            f"{ORCHESTRATOR_MODULE}.build_entry_reconciliation_command",
            side_effect=AssertionError("NoOp must bypass command construction"),
        ) as builder,
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            side_effect=AssertionError("NoOp must bypass confirmation application"),
        ) as applier,
    ):
        result = EntryReconciliationOrchestrator(
            id_factory,
            execution_port,
            repository,
        ).execute(item)

    assert result == snapshot
    assert source_state == snapshot
    assert decide.call_count == 1
    assert decide.call_args.args[0] is item.desired_entry
    assert decide.call_args.args[1] is source_state.current_trade_cycle
    assert id_factory.calls == 0
    builder.assert_not_called()
    assert execution_port.calls == []
    applier.assert_not_called()
    # NoOp never durably saves a pending-recovery marker.
    assert repository.get("instance") == snapshot


def test_apply_reserves_once_and_forwards_exact_command_and_source_snapshot() -> None:
    repository, source_state = seeded_repository()
    snapshot = replace(source_state)
    entry = desired_entry()
    item = projection(source_state, entry)
    confirmation = EntryAppliedConfirmation(
        "instance",
        "cycle-new",
        entry,
        "0.25",
    )
    id_factory = RecordingIdFactory()
    execution_port = FakeExecutionPort(confirmation)

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.build_entry_reconciliation_command",
            wraps=build_entry_reconciliation_command,
        ) as builder,
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
    ):
        result = EntryReconciliationOrchestrator(
            id_factory,
            execution_port,
            repository,
        ).execute(item)

    assert id_factory.calls == 1
    builder.assert_called_once()
    builder_args = builder.call_args.args
    assert builder_args[0] is source_state
    assert builder_args[1] == Apply(entry)
    assert builder_args[2] == "cycle-new"
    assert len(execution_port.calls) == 1
    command, executed_state = execution_port.calls[0]
    assert executed_state is source_state
    assert command == EntryReconciliationCommand(
        "instance",
        "cycle-new",
        "BTCUSDT.P",
        entry,
    )
    applier.assert_called_once()
    applier_args = applier.call_args.args
    assert applier_args[0].pending_entry_recovery == PendingEntryRecovery("cycle-new")
    assert applier_args[0].current_trade_cycle == source_state.current_trade_cycle
    assert applier_args[1] == Apply(entry)
    assert applier_args[2] is command
    assert applier_args[3] is confirmation
    assert source_state == snapshot
    assert source_state.current_trade_cycle is None
    assert result.current_trade_cycle == CurrentTradeCycle(
        "cycle-new",
        AppliedEntryPackage(entry, "0.25"),
    )
    assert result.pending_entry_recovery is None


def test_changed_desired_entry_also_decides_cancel_and_sends_no_desired_entry() -> None:
    original = desired_entry()
    updated = desired_entry(price="101")
    repository, source_state = seeded_repository(applied_entry=original)
    snapshot = replace(source_state)
    item = projection(source_state, updated)
    confirmation = EntryAbsentConfirmation("instance", "cycle-1")
    id_factory = RecordingIdFactory()
    execution_port = FakeExecutionPort(confirmation)

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.build_entry_reconciliation_command",
            wraps=build_entry_reconciliation_command,
        ) as builder,
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
    ):
        result = EntryReconciliationOrchestrator(
            id_factory,
            execution_port,
            repository,
        ).execute(item)

    assert id_factory.calls == 0
    builder.assert_called_once()
    builder_args = builder.call_args.args
    assert builder_args[0] is source_state
    assert builder_args[1] == Cancel("cycle-1")
    assert builder_args[2] is None
    assert len(execution_port.calls) == 1
    command, executed_state = execution_port.calls[0]
    assert command.trade_cycle_id == "cycle-1"
    assert command.desired_entry is None
    assert executed_state is source_state
    applier.assert_called_once()
    assert applier.call_args.args[2] is command
    assert source_state == snapshot
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None


def test_cancel_reuses_cycle_and_clears_the_complete_current_cycle() -> None:
    repository, source_state = seeded_repository(applied_entry=desired_entry())
    snapshot = replace(source_state)
    item = projection(source_state, None)
    confirmation = EntryAbsentConfirmation("instance", "cycle-1")
    id_factory = RecordingIdFactory()
    execution_port = FakeExecutionPort(confirmation)

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.build_entry_reconciliation_command",
            wraps=build_entry_reconciliation_command,
        ) as builder,
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
    ):
        result = EntryReconciliationOrchestrator(
            id_factory,
            execution_port,
            repository,
        ).execute(item)

    assert id_factory.calls == 0
    builder.assert_called_once()
    builder_args = builder.call_args.args
    assert builder_args[0] is source_state
    assert builder_args[1] == Cancel("cycle-1")
    assert builder_args[2] is None
    assert len(execution_port.calls) == 1
    command, executed_state = execution_port.calls[0]
    assert command.trade_cycle_id == "cycle-1"
    assert command.desired_entry is None
    assert executed_state is source_state
    applier.assert_called_once()
    assert applier.call_args.args[2] is command
    assert source_state == snapshot
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None


def test_operation_and_command_contracts_remain_narrow() -> None:
    assert tuple(signature(EntryReconciliationOrchestrator.execute).parameters) == (
        "self",
        "projection",
    )
    assert tuple(field.name for field in fields(EntryReconciliationCommand)) == (
        "strategy_instance_id",
        "trade_cycle_id",
        "ticker",
        "desired_entry",
    )


def test_id_factory_failure_propagates_before_command_or_execution() -> None:
    repository, source_state = seeded_repository()
    snapshot = replace(source_state)
    error = RuntimeError("identity source unavailable")
    id_factory = RecordingIdFactory(error=error)
    execution_port = FakeExecutionPort(object())

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.build_entry_reconciliation_command",
            wraps=build_entry_reconciliation_command,
        ) as builder,
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
        pytest.raises(RuntimeError) as raised,
    ):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, desired_entry())
        )

    assert raised.value is error
    assert id_factory.calls == 1
    builder.assert_not_called()
    assert execution_port.calls == []
    applier.assert_not_called()
    assert source_state == snapshot
    # No command was ever built, so no pending marker was ever saved.
    assert repository.get("instance") == snapshot


@pytest.mark.parametrize("invalid_id", ["", cast("str", None), cast("str", 7)])
def test_invalid_reserved_id_fails_closed_before_external_execution(
    invalid_id: str,
) -> None:
    repository, source_state = seeded_repository()
    snapshot = replace(source_state)
    id_factory = RecordingIdFactory(result=invalid_id)
    execution_port = FakeExecutionPort(object())

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
        pytest.raises(EntryReconciliationInvariantError, match="non-empty"),
    ):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, desired_entry())
        )

    assert id_factory.calls == 1
    assert execution_port.calls == []
    applier.assert_not_called()
    assert source_state == snapshot
    assert repository.get("instance") == snapshot


def test_command_builder_invariant_failure_propagates_without_execution() -> None:
    repository, source_state = seeded_repository()
    snapshot = replace(source_state)
    error = EntryReconciliationInvariantError("forged builder failure")
    id_factory = RecordingIdFactory()
    execution_port = FakeExecutionPort(object())

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.build_entry_reconciliation_command",
            side_effect=error,
        ) as builder,
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
        pytest.raises(EntryReconciliationInvariantError) as raised,
    ):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, desired_entry())
        )

    assert raised.value is error
    assert id_factory.calls == 1
    builder.assert_called_once()
    assert execution_port.calls == []
    applier.assert_not_called()
    assert source_state == snapshot
    assert repository.get("instance") == snapshot


@pytest.mark.parametrize("decision", ["apply", "cancel"])
def test_execution_exception_propagates_once_and_preserves_the_saved_pending_marker(
    decision: str,
) -> None:
    original = desired_entry()
    repository, source_state = seeded_repository(
        applied_entry=None if decision == "apply" else original
    )
    projected = desired_entry() if decision == "apply" else None
    snapshot = replace(source_state)
    error = RuntimeError(f"{decision} execution failed")
    id_factory = RecordingIdFactory()
    execution_port = FakeExecutionPort(object(), error=error)

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
        pytest.raises(RuntimeError) as raised,
    ):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, projected)
        )

    assert raised.value is error
    assert len(execution_port.calls) == 1
    applier.assert_not_called()
    assert id_factory.calls == (1 if decision == "apply" else 0)
    assert source_state == snapshot
    expected_trade_cycle_id = "cycle-new" if decision == "apply" else "cycle-1"
    durable_state = repository.get("instance")
    assert durable_state is not None
    assert durable_state.pending_entry_recovery == PendingEntryRecovery(expected_trade_cycle_id)
    if decision == "apply":
        assert durable_state.current_trade_cycle is None


def test_forged_non_success_result_is_rejected_before_application() -> None:
    repository, source_state = seeded_repository()
    snapshot = replace(source_state)
    execution_port = FakeExecutionPort(object())

    with (
        patch(
            f"{ORCHESTRATOR_MODULE}.apply_success_confirmation",
            wraps=apply_success_confirmation,
        ) as applier,
        pytest.raises(
            EntryReconciliationInvariantError,
            match="must return a successful",
        ),
    ):
        EntryReconciliationOrchestrator(
            RecordingIdFactory(),
            execution_port,
            repository,
        ).execute(projection(source_state, desired_entry()))

    assert len(execution_port.calls) == 1
    applier.assert_not_called()
    assert source_state == snapshot


@pytest.mark.parametrize(
    "confirmation",
    [
        EntryAbsentConfirmation("instance", "cycle-new"),
        EntryAppliedConfirmation(
            "instance",
            "other-cycle",
            desired_entry(),
            "0.25",
        ),
    ],
)
def test_representative_confirmation_invariants_propagate_without_second_execution(
    confirmation: SuccessfulEntryConfirmation,
) -> None:
    repository, source_state = seeded_repository()
    snapshot = replace(source_state)
    execution_port = FakeExecutionPort(confirmation)

    with pytest.raises(EntryReconciliationInvariantError):
        EntryReconciliationOrchestrator(
            RecordingIdFactory(),
            execution_port,
            repository,
        ).execute(projection(source_state, desired_entry()))

    assert len(execution_port.calls) == 1
    assert source_state == snapshot


def test_frozen_entry_context_stops_reconciliation_before_any_execution() -> None:
    entry = desired_entry()
    repository, source_state = seeded_repository(applied_entry=entry)
    assert source_state.current_trade_cycle is not None
    frozen_current_cycle = replace(
        source_state.current_trade_cycle,
        frozen_entry_context=FrozenExecutedEntryContext(
            desired_entry=entry,
            first_fill_at_ms=1_000,
            entry_bar_open_time_ms=900,
        ),
    )
    source_state = repository.save(replace(source_state, current_trade_cycle=frozen_current_cycle))
    snapshot = replace(source_state)
    item = projection(source_state, desired_entry(price="101"))
    execution_port = FakeExecutionPort(object())

    with pytest.raises(EntryReconciliationInvariantError, match="frozen"):
        EntryReconciliationOrchestrator(
            RecordingIdFactory(),
            execution_port,
            repository,
        ).execute(item)

    assert execution_port.calls == []
    assert source_state == snapshot
