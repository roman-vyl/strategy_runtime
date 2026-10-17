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


class EntryAppliedJournalPort(Protocol):
    """Record the entry-order values ABI returned for one applied trade cycle.

    Implementations are best effort and must not raise into orchestration.
    """

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
    ) -> None: ...
