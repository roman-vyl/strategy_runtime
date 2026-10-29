"""Operator commands over one strategy instance: leave the position, cancel the entry order.

Both are overrides of the strategy's own decisions, decided under the instance's mutex (the one
bar processing holds) and both leave the strategy disabled, so it cannot enter again on the next
bar. Close writes `enabled=false` before the exchange action: a close ABI does not confirm leaves
the `pending_close_recovery` marker for the resolver, and the strategy must not re-enter when the
marker is cleared. Cancel keeps the disable order (cancel first, file last).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Protocol

from strategy_runtime.runtime.coordination import (
    StrategyInstanceBusy,
    StrategyInstanceKeyedMutexRegistry,
)
from strategy_runtime.runtime.enabled_control.cancel_step import EntryOrderCancelStep
from strategy_runtime.runtime.enabled_control.errors import (
    AbiUnavailable,
    CatalogUnavailable,
    CycleNotSettled,
    FileChanged,
    IdentityChanged,
    InstanceBusy,
    RecoveryPending,
    StrategyInstanceNotFound,
    WriteFailed,
)
from strategy_runtime.runtime.first_fill.journal import (
    TradeCycleOpenedJournalPort,
    journal_trade_cycle_opened,
)
from strategy_runtime.runtime.first_fill.state_applier import apply_first_fill
from strategy_runtime.runtime.open_position.errors import OpenPositionResolutionError
from strategy_runtime.runtime.open_position.ports import OpenPositionResolverPort
from strategy_runtime.runtime.operator_commands.errors import NoPosition
from strategy_runtime.runtime.operator_commands.models import (
    CancelEntryOrdersResult,
    ClosePositionResult,
)
from strategy_runtime.runtime.position_management_execution import (
    ClosePositionCommand,
    PositionClosedConfirmation,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionError,
)
from strategy_runtime.runtime.position_management_orchestrator.ports import (
    PositionManagementExecutionPort,
)
from strategy_runtime.runtime.state.models import PendingCloseRecovery
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.runtime.trade_cycle_closure import (
    TradeCycleClosedJournalPort,
    journal_trade_cycle_closed,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
    DeploymentFileChanged,
    DeploymentIdentityWouldChange,
    DeploymentNotInCatalog,
    EnabledFileChangeError,
)

DEFAULT_MUTEX_WAIT_SECONDS = 30.0


class _EnabledFileWriter(Protocol):
    def set_enabled(self, strategy_instance_id: str, enabled: bool) -> bool: ...


class StrategyOperatorCommandsService:
    def __init__(
        self,
        *,
        load_snapshot: Callable[[], DeploymentCatalogSnapshot],
        enabled_writer: _EnabledFileWriter,
        state_repository: StrategyInstanceRuntimeStateRepository,
        open_position_resolver: OpenPositionResolverPort,
        position_management_execution: PositionManagementExecutionPort,
        cancel_step: EntryOrderCancelStep,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        mutex_wait_seconds: float = DEFAULT_MUTEX_WAIT_SECONDS,
        trade_cycle_closed_journal: TradeCycleClosedJournalPort | None = None,
        trade_cycle_opened_journal: TradeCycleOpenedJournalPort | None = None,
        entry_order_lifetime_bars: int | None = None,
    ) -> None:
        self._load_snapshot = load_snapshot
        self._enabled_writer = enabled_writer
        self._state_repository = state_repository
        self._open_position_resolver = open_position_resolver
        self._execution = position_management_execution
        self._cancel_step = cancel_step
        self._keyed_mutex_registry = keyed_mutex_registry
        self._mutex_wait_seconds = mutex_wait_seconds
        self._trade_cycle_closed_journal = trade_cycle_closed_journal
        self._trade_cycle_opened_journal = trade_cycle_opened_journal
        self._entry_order_lifetime_bars = entry_order_lifetime_bars

    def close_position(self, strategy_instance_id: str) -> ClosePositionResult:
        self._require_in_catalog(strategy_instance_id)
        with self._locked(strategy_instance_id):
            return self._close_locked(strategy_instance_id)

    def cancel_entry_orders(self, strategy_instance_id: str) -> CancelEntryOrdersResult:
        self._require_in_catalog(strategy_instance_id)
        with self._locked(strategy_instance_id):
            cancelled = self._cancel_step.run(strategy_instance_id)
            self._write_disabled(strategy_instance_id)
            return CancelEntryOrdersResult(strategy_instance_id, False, cancelled)

    @contextmanager
    def _locked(self, strategy_instance_id: str) -> Iterator[None]:
        try:
            with self._keyed_mutex_registry.hold(
                strategy_instance_id, timeout_seconds=self._mutex_wait_seconds
            ):
                yield
        except StrategyInstanceBusy as exc:
            raise InstanceBusy from exc

    def _close_locked(self, strategy_instance_id: str) -> ClosePositionResult:
        state = self._state_repository.get(strategy_instance_id)
        if state is None:
            raise NoPosition
        if state.pending_entry_recovery is not None or state.pending_close_recovery is not None:
            raise RecoveryPending
        cycle = state.current_trade_cycle
        if cycle is None:
            raise NoPosition
        try:
            resolved = self._open_position_resolver.resolve(state)
        except OpenPositionResolutionError as exc:
            raise AbiUnavailable from exc
        if resolved.closure is not None:
            raise CycleNotSettled
        if not resolved.position_open:
            raise NoPosition

        state = resolved.runtime_state
        cycle = state.current_trade_cycle
        assert cycle is not None
        if cycle.frozen_entry_context is None:
            # ABI shows the fill the bar has not frozen yet: freeze it as bar processing does
            assert resolved.first_fill_at_ms is not None
            frozen = apply_first_fill(
                state,
                cycle.trade_cycle_id,
                resolved.first_fill_at_ms,
                order_lifetime_bars=self._entry_order_lifetime_bars,
            )
            state = self._state_repository.save(frozen)
            if (
                resolved.average_entry_price is not None
                and resolved.entry_order_link_id is not None
            ):
                journal_trade_cycle_opened(
                    self._trade_cycle_opened_journal,
                    strategy_instance_id=strategy_instance_id,
                    trade_cycle_id=cycle.trade_cycle_id,
                    bar_open_time_ms=None,
                    first_fill_at_ms=resolved.first_fill_at_ms,
                    average_entry_price=resolved.average_entry_price,
                    entry_order_link_id=resolved.entry_order_link_id,
                    entry_order_id=resolved.entry_order_id,
                )

        self._write_disabled(strategy_instance_id)
        command = ClosePositionCommand(strategy_instance_id, cycle.trade_cycle_id)
        pending = self._state_repository.save(
            replace(state, pending_close_recovery=PendingCloseRecovery(cycle.trade_cycle_id))
        )
        try:
            confirmation = self._execution.close_position(command)
        except PositionManagementExecutionError as exc:
            raise AbiUnavailable from exc
        if (
            type(confirmation) is not PositionClosedConfirmation
            or confirmation.strategy_instance_id != strategy_instance_id
            or confirmation.trade_cycle_id != cycle.trade_cycle_id
        ):
            raise AbiUnavailable
        self._state_repository.save(
            replace(pending, current_trade_cycle=None, pending_close_recovery=None)
        )
        if confirmation.closure is not None:
            journal_trade_cycle_closed(self._trade_cycle_closed_journal, confirmation.closure, None)
        return ClosePositionResult(
            strategy_instance_id,
            cycle.trade_cycle_id,
            False,
            None if confirmation.closure is None else confirmation.closure.reason,
        )

    def _require_in_catalog(self, strategy_instance_id: str) -> None:
        # An unknown id must not reach the mutex registry (it keeps one lock per key).
        try:
            snapshot = self._load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise CatalogUnavailable from exc
        if snapshot.get_by_strategy_instance_id(strategy_instance_id) is None:
            raise StrategyInstanceNotFound

    def _write_disabled(self, strategy_instance_id: str) -> None:
        try:
            self._enabled_writer.set_enabled(strategy_instance_id, False)
        except DeploymentNotInCatalog as exc:
            raise StrategyInstanceNotFound from exc
        except DeploymentFileChanged as exc:
            raise FileChanged from exc
        except DeploymentIdentityWouldChange as exc:
            raise IdentityChanged from exc
        except EnabledFileChangeError as exc:
            raise WriteFailed from exc
