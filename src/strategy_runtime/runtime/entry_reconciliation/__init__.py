"""Pure desired-entry reconciliation boundary."""

from strategy_runtime.runtime.entry_reconciliation.command_builder import (
    build_entry_reconciliation_command,
)
from strategy_runtime.runtime.entry_reconciliation.errors import (
    EntryReconciliationInvariantError,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    Apply,
    Cancel,
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    EntryReconciliationDecision,
    NoOp,
    Replace,
    SuccessfulEntryConfirmation,
)
from strategy_runtime.runtime.entry_reconciliation.reconciliation import (
    decide_entry_reconciliation,
    desired_entries_equivalent,
    get_acknowledged_desired_entry,
)
from strategy_runtime.runtime.entry_reconciliation.state_applier import (
    apply_success_confirmation,
)

__all__ = (
    "Apply",
    "Cancel",
    "EntryAbsentConfirmation",
    "EntryAppliedConfirmation",
    "EntryReconciliationCommand",
    "EntryReconciliationDecision",
    "EntryReconciliationInvariantError",
    "NoOp",
    "Replace",
    "SuccessfulEntryConfirmation",
    "apply_success_confirmation",
    "build_entry_reconciliation_command",
    "decide_entry_reconciliation",
    "desired_entries_equivalent",
    "get_acknowledged_desired_entry",
)
