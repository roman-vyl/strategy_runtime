"""Pure application of successful entry-reconciliation confirmations."""

from dataclasses import replace

from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    Replace,
    SuccessfulEntryConfirmation,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.shared.decimal_text import is_exact_decimal_text


def apply_success_confirmation(
    state: StrategyInstanceRuntimeState,
    decision: Apply | Replace | Cancel,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> StrategyInstanceRuntimeState:
    """Apply one matching formal success or raise the shared invariant error."""
    _require_input_types(state, decision, sent_command, confirmation)
    _require_common_identity(state, sent_command, confirmation)

    if type(decision) is Apply:
        return _apply(state, decision, sent_command, confirmation)
    if type(decision) is Replace:
        return _replace(state, decision, sent_command, confirmation)
    if type(decision) is Cancel:
        return _cancel(state, decision, sent_command, confirmation)
    raise EntryReconciliationInvariantError(
        "confirmation application requires APPLY, REPLACE, or CANCEL"
    )


def _apply(
    state: StrategyInstanceRuntimeState,
    decision: Apply,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> StrategyInstanceRuntimeState:
    if state.current_trade_cycle is not None:
        raise EntryReconciliationInvariantError("APPLY requires no current trade cycle")
    applied = _require_applied_confirmation(confirmation, "APPLY")
    _require_cycle_identity(sent_command.trade_cycle_id, applied.trade_cycle_id)
    _require_matching_desired_entries(
        decision.desired_entry,
        sent_command.desired_entry,
        applied.applied_desired_entry,
    )
    return replace(
        state,
        current_trade_cycle=_confirmed_cycle(applied),
    )


def _replace(
    state: StrategyInstanceRuntimeState,
    decision: Replace,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> StrategyInstanceRuntimeState:
    current_cycle = _require_current_cycle(state, "REPLACE")
    applied = _require_applied_confirmation(confirmation, "REPLACE")
    _require_cycle_identity(current_cycle.trade_cycle_id, decision.trade_cycle_id)
    _require_cycle_identity(decision.trade_cycle_id, sent_command.trade_cycle_id)
    _require_cycle_identity(sent_command.trade_cycle_id, applied.trade_cycle_id)
    _require_matching_desired_entries(
        decision.desired_entry,
        sent_command.desired_entry,
        applied.applied_desired_entry,
    )
    return replace(
        state,
        current_trade_cycle=CurrentTradeCycle(
            trade_cycle_id=current_cycle.trade_cycle_id,
            applied_entry_package=_confirmed_package(applied),
        ),
    )


def _cancel(
    state: StrategyInstanceRuntimeState,
    decision: Cancel,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> StrategyInstanceRuntimeState:
    current_cycle = _require_current_cycle(state, "CANCEL")
    if type(confirmation) is not EntryAbsentConfirmation:
        raise EntryReconciliationInvariantError("CANCEL requires EntryAbsentConfirmation")
    _require_cycle_identity(current_cycle.trade_cycle_id, decision.trade_cycle_id)
    _require_cycle_identity(decision.trade_cycle_id, sent_command.trade_cycle_id)
    _require_cycle_identity(sent_command.trade_cycle_id, confirmation.trade_cycle_id)
    if sent_command.desired_entry is not None:
        raise EntryReconciliationInvariantError(
            "CANCEL requires sent command desired_entry to be null"
        )
    return replace(state, current_trade_cycle=None)


def _require_input_types(
    state: StrategyInstanceRuntimeState,
    decision: Apply | Replace | Cancel,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> None:
    if type(state) is not StrategyInstanceRuntimeState:
        raise EntryReconciliationInvariantError(
            "confirmation application requires StrategyInstanceRuntimeState"
        )
    if type(decision) not in {Apply, Replace, Cancel}:
        raise EntryReconciliationInvariantError(
            "confirmation application requires APPLY, REPLACE, or CANCEL"
        )
    if type(sent_command) is not EntryReconciliationCommand:
        raise EntryReconciliationInvariantError(
            "confirmation application requires EntryReconciliationCommand"
        )
    if type(confirmation) not in {EntryAppliedConfirmation, EntryAbsentConfirmation}:
        raise EntryReconciliationInvariantError(
            "confirmation application requires a successful I3 confirmation"
        )


def _require_common_identity(
    state: StrategyInstanceRuntimeState,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> None:
    if sent_command.strategy_instance_id != state.strategy_instance_id:
        raise EntryReconciliationInvariantError(
            "sent command strategy_instance_id does not match source state"
        )
    if confirmation.strategy_instance_id != state.strategy_instance_id:
        raise EntryReconciliationInvariantError(
            "confirmation strategy_instance_id does not match source state"
        )
    if sent_command.ticker != state.registered_spec_snapshot.instrument:
        raise EntryReconciliationInvariantError(
            "sent command ticker does not match registered instrument"
        )


def _require_applied_confirmation(
    confirmation: SuccessfulEntryConfirmation,
    action: str,
) -> EntryAppliedConfirmation:
    if type(confirmation) is not EntryAppliedConfirmation:
        raise EntryReconciliationInvariantError(f"{action} requires EntryAppliedConfirmation")
    if type(confirmation.applied_desired_entry) is not DesiredEntry:
        raise EntryReconciliationInvariantError(
            "confirmation applied_desired_entry must be DesiredEntry"
        )
    if not is_exact_decimal_text(confirmation.calculated_quantity):
        raise EntryReconciliationInvariantError(
            "confirmation calculated_quantity must be exact-decimal text"
        )
    return confirmation


def _require_current_cycle(
    state: StrategyInstanceRuntimeState,
    action: str,
) -> CurrentTradeCycle:
    current_cycle = state.current_trade_cycle
    if current_cycle is None:
        raise EntryReconciliationInvariantError(
            f"{action} requires an acknowledged current trade cycle"
        )
    return current_cycle


def _require_cycle_identity(expected: str, actual: str) -> None:
    if expected != actual:
        raise EntryReconciliationInvariantError(
            "trade_cycle_id does not match expected trade cycle"
        )


def _require_matching_desired_entries(
    decision_desired_entry: DesiredEntry,
    sent_desired_entry: DesiredEntry | None,
    confirmed_desired_entry: DesiredEntry,
) -> None:
    if (
        type(sent_desired_entry) is not DesiredEntry
        or sent_desired_entry != decision_desired_entry
        or confirmed_desired_entry != decision_desired_entry
    ):
        raise EntryReconciliationInvariantError(
            "desired entry does not match reconciliation decision"
        )


def _confirmed_cycle(confirmation: EntryAppliedConfirmation) -> CurrentTradeCycle:
    return CurrentTradeCycle(
        trade_cycle_id=confirmation.trade_cycle_id,
        applied_entry_package=_confirmed_package(confirmation),
    )


def _confirmed_package(
    confirmation: EntryAppliedConfirmation,
) -> AppliedEntryPackage:
    return AppliedEntryPackage(
        applied_desired_entry=confirmation.applied_desired_entry,
        calculated_quantity=confirmation.calculated_quantity,
    )
