"""External execution boundary for desired-entry reconciliation."""

from typing import Protocol

from strategy_runtime.runtime.entry_reconciliation.models import (
    EntryReconciliationCommand,
    SuccessfulEntryConfirmation,
)
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState


class EntryReconciliationExecutionPort(Protocol):
    """Execute one reconciliation command against its exact source snapshot."""

    def execute(
        self,
        command: EntryReconciliationCommand,
        source_state: StrategyInstanceRuntimeState,
    ) -> SuccessfulEntryConfirmation: ...
