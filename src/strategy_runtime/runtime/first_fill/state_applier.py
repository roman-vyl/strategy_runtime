"""Pure application of the first ABI fill to a strategy-instance aggregate."""

from dataclasses import replace

from strategy_runtime.runtime.first_fill.alignment import align_first_fill_to_entry_bar
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.state.models import (
    FrozenExecutedEntryContext,
    StrategyInstanceRuntimeState,
)


def apply_first_fill(
    state: StrategyInstanceRuntimeState,
    trade_cycle_id: str,
    first_fill_at_ms: int,
) -> StrategyInstanceRuntimeState:
    """Freeze the executed entry context on the first fill for one trade cycle."""
    if type(state) is not StrategyInstanceRuntimeState:
        raise FirstFillInvariantError("apply_first_fill requires StrategyInstanceRuntimeState")
    if type(trade_cycle_id) is not str or len(trade_cycle_id) == 0:
        raise FirstFillInvariantError("apply_first_fill requires a non-empty trade_cycle_id")

    current_cycle = state.current_trade_cycle
    if current_cycle is None:
        raise FirstFillInvariantError("apply_first_fill requires an existing current trade cycle")
    if current_cycle.trade_cycle_id != trade_cycle_id:
        raise FirstFillInvariantError("trade_cycle_id does not match the current trade cycle")
    if type(first_fill_at_ms) is not int or first_fill_at_ms <= 0:
        raise ValueError("first_fill_at_ms must be a strictly positive integer")

    if current_cycle.frozen_entry_context is not None:
        if current_cycle.frozen_entry_context.first_fill_at_ms == first_fill_at_ms:
            return state
        raise FirstFillInvariantError(
            "trade cycle is already frozen with a different first_fill_at_ms"
        )

    entry_bar_open_time_ms = align_first_fill_to_entry_bar(
        first_fill_at_ms, state.registered_spec_snapshot.base_timeframe
    )
    desired_entry = current_cycle.applied_entry_package.applied_desired_entry
    if entry_bar_open_time_ms < desired_entry.source_plan_bar_open_time_ms:
        raise FirstFillInvariantError(
            "entry_bar_open_time_ms precedes the desired entry's source plan bar"
        )

    frozen_context = FrozenExecutedEntryContext(
        desired_entry=desired_entry,
        first_fill_at_ms=first_fill_at_ms,
        entry_bar_open_time_ms=entry_bar_open_time_ms,
    )
    return replace(
        state,
        current_trade_cycle=replace(current_cycle, frozen_entry_context=frozen_context),
    )
