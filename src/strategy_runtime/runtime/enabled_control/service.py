"""Safe enable/disable of one strategy instance (`runtime-strategy-enabled-control-v1`).

The deployment file is the only source of `enabled`. A disable is decided under the
instance's mutex against ABI, and the file is replaced last, after every check and every
exchange action, so a disabled strategy never keeps an order and a failed attempt can be
repeated.
"""

from collections.abc import Callable
from typing import Protocol

from strategy_runtime.runtime.abi.entry_cycle_recovery_ports import AbiEntryCycleRecoveryPort
from strategy_runtime.runtime.coordination import (
    StrategyInstanceBusy,
    StrategyInstanceKeyedMutexRegistry,
)
from strategy_runtime.runtime.enabled_control.cancel_step import EntryOrderCancelStep
from strategy_runtime.runtime.enabled_control.errors import (
    CatalogUnavailable,
    FileChanged,
    IdentityChanged,
    InstanceBusy,
    StrategyInstanceNotFound,
    WriteFailed,
)
from strategy_runtime.runtime.enabled_control.models import EnabledChangeResult
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
        self._cancel_step = EntryOrderCancelStep(
            state_repository=state_repository,
            open_position_resolver=open_position_resolver,
            abi_entry_cycle_recovery=abi_entry_cycle_recovery,
        )
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
        return self._cancel_step.run(strategy_instance_id)

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
