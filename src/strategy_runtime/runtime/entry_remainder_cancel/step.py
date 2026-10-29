"""Bar step: once the frozen lifetime is over, ask ABI to cancel the entry remainder."""

from dataclasses import replace

from strategy_runtime.runtime.entry_order_lifetime import is_entry_order_expired
from strategy_runtime.runtime.entry_remainder_cancel.ports import (
    EntryRemainderCancelJournalPort,
    EntryRemainderCancelPort,
)
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.runtime.timeframe import timeframe_duration_ms


def cancel_expired_entry_remainder(
    state: StrategyInstanceRuntimeState,
    *,
    bar_open_time_ms: int,
    cancel_port: EntryRemainderCancelPort,
    state_repository: StrategyInstanceRuntimeStateRepository,
    journal: EntryRemainderCancelJournalPort | None,
) -> StrategyInstanceRuntimeState:
    """Return the state to continue the bar with; a failed call never raises."""
    cycle = state.current_trade_cycle
    if cycle is None or cycle.entry_remainder_cancelled:
        return state
    frozen_context = cycle.frozen_entry_context
    if frozen_context is None or frozen_context.entry_order_expires_at_bar is None:
        return state
    timeframe_ms = timeframe_duration_ms(state.registered_spec_snapshot.base_timeframe)
    if not is_entry_order_expired(
        bar_open_time_ms, timeframe_ms, frozen_context.entry_order_expires_at_bar
    ):
        return state

    try:
        confirmation = cancel_port.cancel_entry_remainder(
            state.strategy_instance_id, cycle.trade_cycle_id
        )
        saved_state = state_repository.save(
            replace(state, current_trade_cycle=replace(cycle, entry_remainder_cancelled=True))
        )
    except Exception as exc:
        # A failed call or a failed save of the mark: position management continues on
        # this bar with the unchanged state, and the next bar asks again (ABI then answers
        # entry_order_already_terminal).
        if journal is not None:
            journal.entry_remainder_cancel_failed(
                strategy_instance_id=state.strategy_instance_id,
                trade_cycle_id=cycle.trade_cycle_id,
                bar_open_time_ms=bar_open_time_ms,
                error=type(exc).__name__,
            )
        return state

    if journal is not None:
        journal.entry_remainder_cancelled(
            strategy_instance_id=state.strategy_instance_id,
            trade_cycle_id=cycle.trade_cycle_id,
            bar_open_time_ms=bar_open_time_ms,
            status=confirmation.status,
            executed_quantity=confirmation.executed_quantity,
        )
    return saved_state
