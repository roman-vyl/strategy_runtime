"""Safe enable/disable of one strategy instance (`runtime-strategy-enabled-control-v1`).

The deployment file is the only source of `enabled`. A disable is decided under the
instance's mutex against ABI, and the file is replaced last, after every check and every
exchange action, so a disabled strategy never keeps an order and a failed attempt can be
repeated.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from strategy_runtime.runtime.abi.entry_cycle_recovery_ports import AbiEntryCycleRecoveryPort
from strategy_runtime.runtime.abi.entry_package_errors import AbiEntryPackageClientError
from strategy_runtime.runtime.abi.entry_package_models import EntryPackageAbsent
from strategy_runtime.runtime.coordination import (
    StrategyInstanceBusy,
    StrategyInstanceKeyedMutexRegistry,
)
from strategy_runtime.runtime.enabled_control.errors import (
    AbiUnavailable,
    CancelNotConfirmed,
    CatalogUnavailable,
    CycleNotSettled,
    FileChanged,
    IdentityChanged,
    InstanceBusy,
    PositionOpen,
    RecoveryPending,
    StrategyInstanceNotFound,
    WriteFailed,
)
from strategy_runtime.runtime.enabled_control.models import EnabledChangeResult
from strategy_runtime.runtime.open_position.errors import OpenPositionResolutionError
from strategy_runtime.runtime.open_position.ports import OpenPositionResolverPort
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
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


class StrategyEnabledControlService:
    def __init__(
        self,
        *,
        load_snapshot: Callable[[], DeploymentCatalogSnapshot],
        enabled_writer: _EnabledFileWriter,
        state_repository: StrategyInstanceRuntimeStateRepository,
        open_position_resolver: OpenPositionResolverPort,
        abi_entry_cycle_recovery: AbiEntryCycleRecoveryPort,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        mutex_wait_seconds: float = DEFAULT_MUTEX_WAIT_SECONDS,
    ) -> None:
        self._load_snapshot = load_snapshot
        self._enabled_writer = enabled_writer
        self._state_repository = state_repository
        self._open_position_resolver = open_position_resolver
        self._abi_entry_cycle_recovery = abi_entry_cycle_recovery
        self._keyed_mutex_registry = keyed_mutex_registry
        self._mutex_wait_seconds = mutex_wait_seconds

    def set_enabled(self, strategy_instance_id: str, enabled: bool) -> EnabledChangeResult:
        # An unknown id must not reach the mutex registry (it keeps one lock per key).
        self._current_enabled(strategy_instance_id)
        try:
            with self._keyed_mutex_registry.hold(
                strategy_instance_id, timeout_seconds=self._mutex_wait_seconds
            ):
                return self._set_enabled_locked(strategy_instance_id, enabled)
        except StrategyInstanceBusy as exc:
            raise InstanceBusy from exc

    def _set_enabled_locked(self, strategy_instance_id: str, enabled: bool) -> EnabledChangeResult:
        if self._current_enabled(strategy_instance_id) is enabled:
            return EnabledChangeResult(strategy_instance_id, enabled, False)
        cancelled = False if enabled else self._cancel_entry_order_if_any(strategy_instance_id)
        self._write(strategy_instance_id, enabled)
        return EnabledChangeResult(strategy_instance_id, enabled, cancelled)

    def _current_enabled(self, strategy_instance_id: str) -> bool:
        try:
            snapshot = self._load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise CatalogUnavailable from exc
        deployment = snapshot.get_by_strategy_instance_id(strategy_instance_id)
        if deployment is None:
            raise StrategyInstanceNotFound
        return deployment.enabled

    def _cancel_entry_order_if_any(self, strategy_instance_id: str) -> bool:
        """Refuse when a position or recovery is open; cancel a resting entry order."""
        state = self._state_repository.get(strategy_instance_id)
        if state is None:
            return False
        if state.pending_entry_recovery is not None or state.pending_close_recovery is not None:
            raise RecoveryPending
        cycle = state.current_trade_cycle
        if cycle is None:
            return False

        try:
            resolved = self._open_position_resolver.resolve(state)
        except OpenPositionResolutionError as exc:
            raise AbiUnavailable from exc
        if resolved.position_open:
            raise PositionOpen
        if resolved.closure is not None:
            raise CycleNotSettled

        try:
            cancel_result = self._abi_entry_cycle_recovery.cancel(
                strategy_instance_id,
                cycle.trade_cycle_id,
                state.registered_spec_snapshot.instrument,
                state.risk_multiplier,
            )
        except AbiEntryPackageClientError as exc:
            raise AbiUnavailable from exc
        if not (
            type(cancel_result) is EntryPackageAbsent
            and cancel_result.strategy_instance_id == strategy_instance_id
            and cancel_result.trade_cycle_id == cycle.trade_cycle_id
        ):
            raise CancelNotConfirmed
        self._state_repository.save(replace(state, current_trade_cycle=None))
        return True

    def _write(self, strategy_instance_id: str, enabled: bool) -> None:
        try:
            self._enabled_writer.set_enabled(strategy_instance_id, enabled)
        except DeploymentNotInCatalog as exc:
            raise StrategyInstanceNotFound from exc
        except DeploymentFileChanged as exc:
            raise FileChanged from exc
        except DeploymentIdentityWouldChange as exc:
            raise IdentityChanged from exc
        except EnabledFileChangeError as exc:
            raise WriteFailed from exc
