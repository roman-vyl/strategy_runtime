"""Pure desired-entry equivalence and decision selection."""

from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryReconciliationDecision,
    NoOp,
    Replace,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import CurrentTradeCycle


def get_acknowledged_desired_entry(
    current_trade_cycle: CurrentTradeCycle | None,
) -> DesiredEntry | None:
    """Return the singular acknowledged desired entry, if a current cycle exists."""
    if current_trade_cycle is None:
        return None
    if type(current_trade_cycle) is not CurrentTradeCycle:
        raise TypeError("current_trade_cycle must be CurrentTradeCycle or None")
    return current_trade_cycle.applied_entry_package.applied_desired_entry


def desired_entries_equivalent(left: DesiredEntry, right: DesiredEntry) -> bool:
    """Compare complete canonical DesiredEntry domain values exactly."""
    if type(left) is not DesiredEntry or type(right) is not DesiredEntry:
        raise TypeError("desired-entry equivalence requires DesiredEntry values")
    return left == right


def decide_entry_reconciliation(
    new_desired_entry: DesiredEntry | None,
    current_trade_cycle: CurrentTradeCycle | None,
) -> EntryReconciliationDecision:
    """Select the complete payload-bearing reconciliation decision."""
    if new_desired_entry is not None and type(new_desired_entry) is not DesiredEntry:
        raise TypeError("new_desired_entry must be DesiredEntry or None")
    if current_trade_cycle is not None and current_trade_cycle.frozen_entry_context is not None:
        raise EntryReconciliationInvariantError(
            "entry reconciliation is fail-closed once the trade cycle's entry is frozen"
        )

    acknowledged_desired_entry = get_acknowledged_desired_entry(current_trade_cycle)
    if acknowledged_desired_entry is None:
        if new_desired_entry is None:
            return NoOp()
        return Apply(new_desired_entry)

    assert current_trade_cycle is not None
    if new_desired_entry is None:
        return Cancel(current_trade_cycle.trade_cycle_id)
    if desired_entries_equivalent(new_desired_entry, acknowledged_desired_entry):
        return NoOp()
    return Replace(current_trade_cycle.trade_cycle_id, new_desired_entry)
