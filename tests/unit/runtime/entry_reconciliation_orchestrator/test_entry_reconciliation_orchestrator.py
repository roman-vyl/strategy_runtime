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
    EntryDeclinedOutcome,
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


class ScriptedExecutionPort:
    """Returns (or raises) one scripted outcome per call, in order."""

    def __init__(self, *outcomes: SuccessfulEntryConfirmation | Exception | object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[EntryReconciliationCommand, StrategyInstanceRuntimeState]] = []

    def execute(
        self,
        command: EntryReconciliationCommand,
        source_state: StrategyInstanceRuntimeState,
    ) -> SuccessfulEntryConfirmation:
        self.calls.append((command, source_state))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return cast("SuccessfulEntryConfirmation", outcome)


class SaveRecordingRepository(InMemoryStrategyInstanceRuntimeStateRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saved: list[StrategyInstanceRuntimeState] = []

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        self.saved.append(state)
        return super().save(state)


def seeded_recording_repository(
    applied_entry: DesiredEntry,
) -> tuple[SaveRecordingRepository, StrategyInstanceRuntimeState]:
    repository = SaveRecordingRepository()
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
    state = repository.save(
        replace(
            state,
            current_trade_cycle=CurrentTradeCycle(
                "cycle-1",
                AppliedEntryPackage(applied_entry, "0.01"),
            ),
        )
    )
    repository.saved.clear()
    return repository, state


def replace_applied_confirmation(
    entry: DesiredEntry, cycle: str = "cycle-new"
) -> EntryAppliedConfirmation:
    return EntryAppliedConfirmation("instance", cycle, entry, "0.02")


def test_changed_desired_entry_replaces_in_one_invocation() -> None:
    original = desired_entry()
    updated = desired_entry(price="101")
    repository, source_state = seeded_recording_repository(original)
    snapshot = replace(source_state)
    id_factory = RecordingIdFactory()
    execution_port = ScriptedExecutionPort(
        EntryAbsentConfirmation("instance", "cycle-1"),
        replace_applied_confirmation(updated),
    )

    result = EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
        projection(source_state, updated)
    )

    assert id_factory.calls == 1
    assert [(c.trade_cycle_id, c.desired_entry) for c, _ in execution_port.calls] == [
        ("cycle-1", None),
        ("cycle-new", updated),
    ]
    assert execution_port.calls[0][1] is source_state
    assert execution_port.calls[1][1].current_trade_cycle is None
    # Marker C on cycle C, then the boundary save: no cycle, marker N.
    assert [(s.current_trade_cycle, s.pending_entry_recovery) for s in repository.saved] == [
        (source_state.current_trade_cycle, PendingEntryRecovery("cycle-1")),
        (None, PendingEntryRecovery("cycle-new")),
    ]
    assert result.current_trade_cycle == CurrentTradeCycle(
        "cycle-new", AppliedEntryPackage(updated, "0.02")
    )
    assert result.pending_entry_recovery is None
    assert source_state == snapshot


def test_replace_reserves_the_new_identity_only_after_confirmed_absence() -> None:
    repository, source_state = seeded_recording_repository(desired_entry())
    id_factory = RecordingIdFactory()
    seen_calls_at_reservation: list[int] = []
    execution_port = ScriptedExecutionPort(
        EntryAbsentConfirmation("instance", "cycle-1"),
        replace_applied_confirmation(desired_entry(price="101")),
    )

    def reserve() -> str:
        seen_calls_at_reservation.append(len(execution_port.calls))
        return id_factory()

    EntryReconciliationOrchestrator(reserve, execution_port, repository).execute(
        projection(source_state, desired_entry(price="101"))
    )

    assert seen_calls_at_reservation == [1]


@pytest.mark.parametrize(
    "cancel_outcome",
    [
        RuntimeError("ABI entry-package request timed out"),
        object(),
    ],
)
def test_replace_sends_no_apply_when_cancel_is_not_confirmed(
    cancel_outcome: Exception | object,
) -> None:
    repository, source_state = seeded_recording_repository(desired_entry())
    id_factory = RecordingIdFactory()
    execution_port = ScriptedExecutionPort(cancel_outcome)

    with pytest.raises((RuntimeError, EntryReconciliationInvariantError)):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, desired_entry(price="101"))
        )

    assert id_factory.calls == 0
    assert len(execution_port.calls) == 1
    durable = repository.get("instance")
    assert durable is not None
    assert durable.current_trade_cycle == source_state.current_trade_cycle
    assert durable.pending_entry_recovery == PendingEntryRecovery("cycle-1")


def test_replace_rejects_a_contradictory_absent_confirmation_without_apply() -> None:
    repository, source_state = seeded_recording_repository(desired_entry())
    id_factory = RecordingIdFactory()
    execution_port = ScriptedExecutionPort(EntryAbsentConfirmation("instance", "other-cycle"))

    with pytest.raises(EntryReconciliationInvariantError):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, desired_entry(price="101"))
        )

    assert id_factory.calls == 0
    assert len(execution_port.calls) == 1


@pytest.mark.parametrize(
    "apply_outcome",
    [
        RuntimeError("ABI entry-package request timed out"),
        EntryAppliedConfirmation("instance", "other-cycle", desired_entry(price="101"), "0.02"),
    ],
)
def test_replace_apply_failure_leaves_the_boundary_state_without_retry(
    apply_outcome: Exception | object,
) -> None:
    repository, source_state = seeded_recording_repository(desired_entry())
    id_factory = RecordingIdFactory()
    execution_port = ScriptedExecutionPort(
        EntryAbsentConfirmation("instance", "cycle-1"), apply_outcome
    )

    with pytest.raises((RuntimeError, EntryReconciliationInvariantError)):
        EntryReconciliationOrchestrator(id_factory, execution_port, repository).execute(
            projection(source_state, desired_entry(price="101"))
        )

    assert len(execution_port.calls) == 2
    durable = repository.get("instance")
    assert durable is not None
    assert durable.current_trade_cycle is None
    assert durable.pending_entry_recovery == PendingEntryRecovery("cycle-new")


def test_five_bars_of_changing_entries_keep_an_order_on_every_bar() -> None:
    repository, state = seeded_recording_repository(desired_entry(price="100"))
    ids = iter(f"cycle-{n}" for n in range(2, 7))
    prices = ["101", "102", "103", "104", "105"]
    outcomes: list[object] = []
    previous = "cycle-1"
    for n, price in zip(range(2, 7), prices, strict=True):
        outcomes.append(EntryAbsentConfirmation("instance", previous))
        outcomes.append(replace_applied_confirmation(desired_entry(price=price), f"cycle-{n}"))
        previous = f"cycle-{n}"
    execution_port = ScriptedExecutionPort(*outcomes)
    orchestrator = EntryReconciliationOrchestrator(lambda: next(ids), execution_port, repository)

    for price in prices:
        state = repository.save(orchestrator.execute(projection(state, desired_entry(price=price))))
        cycle = state.current_trade_cycle
        assert cycle is not None
        assert cycle.applied_entry_package.applied_desired_entry == desired_entry(price=price)
        assert state.pending_entry_recovery is None

    assert [c.desired_entry is None for c, _ in execution_port.calls] == [True, False] * 5


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


class RecordingAppliedJournal:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, str | int | None]] = []

    def entry_package_applied(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int,
        trigger_price: str | None,
        stop_loss: str | None,
        take_profit: str | None,
        quantity: str | None,
        order_link_id: str | None,
        order_id: str | None,
    ) -> None:
        self.calls.append(
            {
                "strategy_instance_id": strategy_instance_id,
                "trade_cycle_id": trade_cycle_id,
                "bar_open_time_ms": bar_open_time_ms,
                "trigger_price": trigger_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "quantity": quantity,
                "order_link_id": order_link_id,
                "order_id": order_id,
            }
        )
        if self.error is not None:
            raise self.error


def applied_confirmation(**values: str | None) -> EntryAppliedConfirmation:
    entry = desired_entry(price="105")
    return EntryAppliedConfirmation("instance", "cycle-new", entry, "0.01", **values)


def run_with_journal(
    confirmation: SuccessfulEntryConfirmation,
    journal: RecordingAppliedJournal,
    new_entry: DesiredEntry | None,
    *,
    applied_entry: DesiredEntry | None = None,
) -> StrategyInstanceRuntimeState:
    repository, source_state = seeded_repository(applied_entry=applied_entry)
    return EntryReconciliationOrchestrator(
        RecordingIdFactory(),
        FakeExecutionPort(confirmation),
        repository,
        entry_applied_journal=journal,
    ).execute(projection(source_state, new_entry))


def test_applied_confirmation_with_values_is_journaled_once() -> None:
    journal = RecordingAppliedJournal()
    new_entry = desired_entry(price="105")

    run_with_journal(
        applied_confirmation(
            trigger_price="105", stop_loss="99", take_profit="110", quantity="0.01"
        ),
        journal,
        new_entry,
    )

    assert journal.calls == [
        {
            "strategy_instance_id": "instance",
            "trade_cycle_id": "cycle-new",
            "bar_open_time_ms": 1000,
            "trigger_price": "105",
            "stop_loss": "99",
            "take_profit": "110",
            "quantity": "0.01",
            "order_link_id": None,
            "order_id": None,
        }
    ]


def test_applied_identifiers_are_journaled_with_the_processing_bar() -> None:
    journal = RecordingAppliedJournal()

    run_with_journal(
        applied_confirmation(order_link_id="link-1", order_id="bybit-1"),
        journal,
        desired_entry(price="105"),
    )

    assert len(journal.calls) == 1
    call = journal.calls[0]
    assert call["bar_open_time_ms"] == 1000
    assert (call["order_link_id"], call["order_id"]) == ("link-1", "bybit-1")
    assert call["trigger_price"] is None


def test_old_shape_confirmation_writes_no_event() -> None:
    journal = RecordingAppliedJournal()

    run_with_journal(applied_confirmation(), journal, desired_entry(price="105"))

    assert journal.calls == []


def test_absent_confirmation_writes_no_event() -> None:
    journal = RecordingAppliedJournal()

    run_with_journal(
        EntryAbsentConfirmation("instance", "cycle-1"),
        journal,
        None,
        applied_entry=desired_entry(),
    )

    assert journal.calls == []


def test_failing_execution_writes_no_event() -> None:
    journal = RecordingAppliedJournal()
    repository, source_state = seeded_repository()

    with pytest.raises(RuntimeError, match="abi down"):
        EntryReconciliationOrchestrator(
            RecordingIdFactory(),
            FakeExecutionPort(object(), error=RuntimeError("abi down")),
            repository,
            entry_applied_journal=journal,
        ).execute(projection(source_state, desired_entry(price="105")))

    assert journal.calls == []


def test_journaled_values_do_not_change_the_resulting_state() -> None:
    new_entry = desired_entry(price="105")
    without = run_with_journal(applied_confirmation(), RecordingAppliedJournal(), new_entry)
    with_values = run_with_journal(
        applied_confirmation(
            trigger_price="105", stop_loss="99", take_profit="110", quantity="0.01"
        ),
        RecordingAppliedJournal(),
        new_entry,
    )

    assert with_values == without


class RecordingDeclinedJournal:
    def __init__(self, repository: SaveRecordingRepository | None = None) -> None:
        self.repository = repository
        self.calls: list[dict[str, str | int]] = []
        self.saves_seen: list[int] = []

    def entry_package_declined(
        self,
        *,
        strategy_instance_id: str,
        trade_cycle_id: str,
        bar_open_time_ms: int,
        risk_multiplier: str,
        decline_reason: str,
        decline_message: str,
    ) -> None:
        if self.repository is not None:
            self.saves_seen.append(len(self.repository.saved))
        self.calls.append(
            {
                "strategy_instance_id": strategy_instance_id,
                "trade_cycle_id": trade_cycle_id,
                "bar_open_time_ms": bar_open_time_ms,
                "risk_multiplier": risk_multiplier,
                "decline_reason": decline_reason,
                "decline_message": decline_message,
            }
        )


def declined(cycle: str = "cycle-new", instance: str = "instance") -> EntryDeclinedOutcome:
    return EntryDeclinedOutcome(
        instance,
        cycle,
        "insufficient_balance_for_minimum_quantity",
        "quantity 0.0004 below minOrderQty 0.001",
    )


def unseeded_recording_repository() -> tuple[SaveRecordingRepository, StrategyInstanceRuntimeState]:
    repository = SaveRecordingRepository()
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
    repository.saved.clear()
    return repository, state


def test_declined_apply_ends_without_cycle_and_durably_clears_the_marker() -> None:
    repository, source_state = unseeded_recording_repository()
    journal = RecordingDeclinedJournal(repository)
    execution_port = ScriptedExecutionPort(declined())

    result = EntryReconciliationOrchestrator(
        RecordingIdFactory(),
        execution_port,
        repository,
        entry_declined_journal=journal,
    ).execute(projection(source_state, desired_entry()))

    assert len(execution_port.calls) == 1
    assert [(s.current_trade_cycle, s.pending_entry_recovery) for s in repository.saved] == [
        (None, PendingEntryRecovery("cycle-new")),
        (None, None),
    ]
    stored = repository.get("instance")
    assert stored is not None
    assert stored.pending_entry_recovery is None
    assert stored.current_trade_cycle is None
    assert result == stored
    # Equal to the bar's source state, so the caller will not save it again.
    assert result == source_state
    assert journal.saves_seen == [2]
    assert journal.calls == [
        {
            "strategy_instance_id": "instance",
            "trade_cycle_id": "cycle-new",
            "bar_open_time_ms": 1000,
            "risk_multiplier": source_state.risk_multiplier,
            "decline_reason": "insufficient_balance_for_minimum_quantity",
            "decline_message": "quantity 0.0004 below minOrderQty 0.001",
        }
    ]


def test_declined_apply_without_journal_still_clears_the_marker() -> None:
    repository, source_state = unseeded_recording_repository()

    result = EntryReconciliationOrchestrator(
        RecordingIdFactory(), ScriptedExecutionPort(declined()), repository
    ).execute(projection(source_state, desired_entry()))

    assert result.pending_entry_recovery is None
    stored = repository.get("instance")
    assert stored is not None and stored.pending_entry_recovery is None


def test_replace_with_declined_apply_leaves_no_cycle_and_no_marker() -> None:
    original = desired_entry()
    updated = desired_entry(price="101")
    repository, source_state = seeded_recording_repository(original)
    journal = RecordingDeclinedJournal()
    execution_port = ScriptedExecutionPort(
        EntryAbsentConfirmation("instance", "cycle-1"),
        declined(),
    )

    result = EntryReconciliationOrchestrator(
        RecordingIdFactory(), execution_port, repository, entry_declined_journal=journal
    ).execute(projection(source_state, updated))

    assert [(c.trade_cycle_id, c.desired_entry) for c, _ in execution_port.calls] == [
        ("cycle-1", None),
        ("cycle-new", updated),
    ]
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None
    assert repository.saved[-1] == result
    assert [call["trade_cycle_id"] for call in journal.calls] == ["cycle-new"]


def test_next_bar_after_a_decline_sends_a_new_apply() -> None:
    repository, source_state = unseeded_recording_repository()
    entry = desired_entry()
    first = EntryReconciliationOrchestrator(
        RecordingIdFactory("cycle-a"), ScriptedExecutionPort(declined("cycle-a")), repository
    ).execute(projection(source_state, entry))

    execution_port = ScriptedExecutionPort(replace_applied_confirmation(entry, "cycle-b"))
    second = EntryReconciliationOrchestrator(
        RecordingIdFactory("cycle-b"), execution_port, repository
    ).execute(projection(first, entry))

    assert [c.trade_cycle_id for c, _ in execution_port.calls] == ["cycle-b"]
    assert second.current_trade_cycle == CurrentTradeCycle(
        "cycle-b", AppliedEntryPackage(entry, "0.02")
    )
    assert second.pending_entry_recovery is None


def test_declined_outcome_for_a_cancel_is_an_invariant_error() -> None:
    repository, source_state = seeded_recording_repository(desired_entry())
    journal = RecordingDeclinedJournal()

    with pytest.raises(EntryReconciliationInvariantError):
        EntryReconciliationOrchestrator(
            RecordingIdFactory(),
            ScriptedExecutionPort(declined("cycle-1")),
            repository,
            entry_declined_journal=journal,
        ).execute(projection(source_state, None))

    assert [s.pending_entry_recovery for s in repository.saved] == [PendingEntryRecovery("cycle-1")]
    assert journal.calls == []


@pytest.mark.parametrize(
    "outcome",
    [declined(cycle="cycle-other"), declined(instance="instance-other")],
)
def test_declined_outcome_with_mismatched_identity_is_an_invariant_error(
    outcome: EntryDeclinedOutcome,
) -> None:
    repository, source_state = unseeded_recording_repository()
    journal = RecordingDeclinedJournal()

    with pytest.raises(EntryReconciliationInvariantError):
        EntryReconciliationOrchestrator(
            RecordingIdFactory(),
            ScriptedExecutionPort(outcome),
            repository,
            entry_declined_journal=journal,
        ).execute(projection(source_state, desired_entry()))

    assert [s.pending_entry_recovery for s in repository.saved] == [
        PendingEntryRecovery("cycle-new")
    ]
    assert journal.calls == []


def test_applied_and_absent_write_no_declined_event() -> None:
    journal = RecordingDeclinedJournal()
    repository, source_state = seeded_repository()
    EntryReconciliationOrchestrator(
        RecordingIdFactory(),
        FakeExecutionPort(applied_confirmation()),
        repository,
        entry_declined_journal=journal,
    ).execute(projection(source_state, desired_entry(price="105")))
    assert journal.calls == []
