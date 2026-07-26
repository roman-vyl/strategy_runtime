"""Pure construction of I3 desired-entry reconciliation commands."""

from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryReconciliationCommand,
    EntryReconciliationDecision,
    NoOp,
    Replace,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState


def build_entry_reconciliation_command(
    state: StrategyInstanceRuntimeState,
    decision: EntryReconciliationDecision,
    apply_trade_cycle_id: str | None = None,
) -> EntryReconciliationCommand | None:
    """Build one coherent command, return no command for NoOp, or fail closed."""
    if type(state) is not StrategyInstanceRuntimeState:
        raise EntryReconciliationInvariantError(
            "command construction requires StrategyInstanceRuntimeState"
        )

    if type(decision) is NoOp:
        if apply_trade_cycle_id is not None:
            raise EntryReconciliationInvariantError("NO_OP prohibits apply_trade_cycle_id")
        return None

    if type(decision) is Apply:
        if state.current_trade_cycle is not None:
            raise EntryReconciliationInvariantError("APPLY requires no current trade cycle")
        _require_apply_trade_cycle_id(apply_trade_cycle_id)
        assert apply_trade_cycle_id is not None
        return _command(state, apply_trade_cycle_id, decision.desired_entry)

    if apply_trade_cycle_id is not None:
        raise EntryReconciliationInvariantError("only APPLY accepts apply_trade_cycle_id")

    if type(decision) is Replace:
        _require_current_cycle(state, decision.trade_cycle_id, "REPLACE")
        return _command(state, decision.trade_cycle_id, decision.desired_entry)

    if type(decision) is Cancel:
        _require_current_cycle(state, decision.trade_cycle_id, "CANCEL")
        return _command(state, decision.trade_cycle_id, None)

    raise EntryReconciliationInvariantError("unknown entry reconciliation decision")


def _command(
    state: StrategyInstanceRuntimeState,
    trade_cycle_id: str,
    desired_entry: DesiredEntry | None,
) -> EntryReconciliationCommand:
    return EntryReconciliationCommand(
        strategy_instance_id=state.strategy_instance_id,
        trade_cycle_id=trade_cycle_id,
        ticker=state.registered_spec_snapshot.instrument,
        desired_entry=desired_entry,
    )


def _require_apply_trade_cycle_id(apply_trade_cycle_id: str | None) -> None:
    if type(apply_trade_cycle_id) is not str or len(apply_trade_cycle_id) == 0:
        raise EntryReconciliationInvariantError("APPLY requires a non-empty apply_trade_cycle_id")


def _require_current_cycle(
    state: StrategyInstanceRuntimeState,
    decision_trade_cycle_id: str,
    action: str,
) -> None:
    current_cycle = state.current_trade_cycle
    if current_cycle is None:
        raise EntryReconciliationInvariantError(
            f"{action} requires an acknowledged current trade cycle"
        )
    if current_cycle.trade_cycle_id != decision_trade_cycle_id:
        raise EntryReconciliationInvariantError(
            f"{action} trade_cycle_id does not match current trade cycle"
        )
