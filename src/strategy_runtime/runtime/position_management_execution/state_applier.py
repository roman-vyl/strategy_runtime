"""Pure application of successful position-management execution confirmations."""

from dataclasses import replace

from strategy_runtime.runtime.position_management_decision.models import (
    ApplyProtection,
    ClosePosition,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionInvariantError,
)
from strategy_runtime.runtime.position_management_execution.models import (
    ApplyProtectionCommand,
    ClosePositionCommand,
    PositionClosedConfirmation,
    PositionManagementExecutionCommand,
    PositionManagementExecutionConfirmation,
    ProtectionAppliedConfirmation,
)
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.state.models import CurrentTradeCycle, StrategyInstanceRuntimeState


def apply_position_management_confirmation(
    state: StrategyInstanceRuntimeState,
    decision: ApplyProtection | ClosePosition,
    sent_command: PositionManagementExecutionCommand,
    confirmation: PositionManagementExecutionConfirmation,
) -> StrategyInstanceRuntimeState:
    """Apply one matching confirmation or raise the shared invariant error."""
    _require_input_types(state, decision, sent_command, confirmation)
    _require_common_identity(state, sent_command, confirmation)

    if type(decision) is ApplyProtection:
        return _apply_protection(state, decision, sent_command, confirmation)
    if type(decision) is ClosePosition:
        return _close_position(state, decision, sent_command, confirmation)
    raise PositionManagementExecutionInvariantError(
        "confirmation application requires APPLY_PROTECTION or CLOSE_POSITION"
    )


def _apply_protection(
    state: StrategyInstanceRuntimeState,
    decision: ApplyProtection,
    sent_command: PositionManagementExecutionCommand,
    confirmation: PositionManagementExecutionConfirmation,
) -> StrategyInstanceRuntimeState:
    current_cycle = _require_current_cycle(state, "APPLY_PROTECTION")
    if type(sent_command) is not ApplyProtectionCommand:
        raise PositionManagementExecutionInvariantError(
            "APPLY_PROTECTION requires ApplyProtectionCommand"
        )
    if type(confirmation) is not ProtectionAppliedConfirmation:
        raise PositionManagementExecutionInvariantError(
            "APPLY_PROTECTION requires ProtectionAppliedConfirmation"
        )
    _require_cycle_identity(current_cycle.trade_cycle_id, decision.trade_cycle_id)
    _require_cycle_identity(decision.trade_cycle_id, sent_command.trade_cycle_id)
    _require_cycle_identity(sent_command.trade_cycle_id, confirmation.trade_cycle_id)
    _require_matching_protection(
        decision.desired_protection,
        sent_command.desired_protection,
        confirmation.confirmed_protection,
    )
    return replace(
        state,
        current_trade_cycle=replace(
            current_cycle,
            latest_confirmed_management_protection=confirmation.confirmed_protection,
        ),
    )


def _close_position(
    state: StrategyInstanceRuntimeState,
    decision: ClosePosition,
    sent_command: PositionManagementExecutionCommand,
    confirmation: PositionManagementExecutionConfirmation,
) -> StrategyInstanceRuntimeState:
    current_cycle = _require_current_cycle(state, "CLOSE_POSITION")
    if type(sent_command) is not ClosePositionCommand:
        raise PositionManagementExecutionInvariantError(
            "CLOSE_POSITION requires ClosePositionCommand"
        )
    if type(confirmation) is not PositionClosedConfirmation:
        raise PositionManagementExecutionInvariantError(
            "CLOSE_POSITION requires PositionClosedConfirmation"
        )
    _require_cycle_identity(current_cycle.trade_cycle_id, decision.trade_cycle_id)
    _require_cycle_identity(decision.trade_cycle_id, sent_command.trade_cycle_id)
    _require_cycle_identity(sent_command.trade_cycle_id, confirmation.trade_cycle_id)
    return replace(state, current_trade_cycle=None)


def _require_input_types(
    state: StrategyInstanceRuntimeState,
    decision: ApplyProtection | ClosePosition,
    sent_command: PositionManagementExecutionCommand,
    confirmation: PositionManagementExecutionConfirmation,
) -> None:
    if type(state) is not StrategyInstanceRuntimeState:
        raise PositionManagementExecutionInvariantError(
            "confirmation application requires StrategyInstanceRuntimeState"
        )
    if type(decision) not in {ApplyProtection, ClosePosition}:
        raise PositionManagementExecutionInvariantError(
            "confirmation application requires APPLY_PROTECTION or CLOSE_POSITION"
        )
    if type(sent_command) not in {ApplyProtectionCommand, ClosePositionCommand}:
        raise PositionManagementExecutionInvariantError(
            "confirmation application requires a position-management execution command"
        )
    if type(confirmation) not in {ProtectionAppliedConfirmation, PositionClosedConfirmation}:
        raise PositionManagementExecutionInvariantError(
            "confirmation application requires a position-management execution confirmation"
        )


def _require_common_identity(
    state: StrategyInstanceRuntimeState,
    sent_command: PositionManagementExecutionCommand,
    confirmation: PositionManagementExecutionConfirmation,
) -> None:
    if sent_command.strategy_instance_id != state.strategy_instance_id:
        raise PositionManagementExecutionInvariantError(
            "sent command strategy_instance_id does not match source state"
        )
    if confirmation.strategy_instance_id != state.strategy_instance_id:
        raise PositionManagementExecutionInvariantError(
            "confirmation strategy_instance_id does not match source state"
        )


def _require_current_cycle(
    state: StrategyInstanceRuntimeState,
    action: str,
) -> CurrentTradeCycle:
    current_cycle = state.current_trade_cycle
    if current_cycle is None:
        raise PositionManagementExecutionInvariantError(
            f"{action} requires an acknowledged current trade cycle"
        )
    return current_cycle


def _require_cycle_identity(expected: str, actual: str) -> None:
    if expected != actual:
        raise PositionManagementExecutionInvariantError(
            "trade_cycle_id does not match expected trade cycle"
        )


def _require_matching_protection(
    decision_desired_protection: DesiredProtection,
    sent_desired_protection: DesiredProtection,
    confirmed_protection: DesiredProtection,
) -> None:
    if (
        sent_desired_protection != decision_desired_protection
        or confirmed_protection != decision_desired_protection
    ):
        raise PositionManagementExecutionInvariantError(
            "confirmed protection does not match the position-management decision"
        )
