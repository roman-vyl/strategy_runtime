"""Safe delete of one strategy instance (`runtime-strategy-delete-v1`).

Delete removes a strategy that is already safely stopped: its file must say `enabled: false`.
The disable's checks are repeated under the instance's mutex as a safety net, because the flag
is only text on disk; the deployment file moves to the trash last.
"""

from collections.abc import Callable
from typing import Protocol

from strategy_runtime.runtime.coordination import (
    StrategyInstanceBusy,
    StrategyInstanceKeyedMutexRegistry,
)
from strategy_runtime.runtime.enabled_control.cancel_step import EntryOrderCancelStep
from strategy_runtime.runtime.enabled_control.errors import (
    CatalogUnavailable,
    FileChanged,
    InstanceBusy,
    StrategyInstanceNotFound,
)
from strategy_runtime.runtime.strategy_delete.errors import MoveFailed, StillEnabled, TrashNameTaken
from strategy_runtime.runtime.strategy_delete.models import DeleteResult
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
    DeploymentFileChanged,
    DeploymentNotInCatalog,
    DeploymentTrashMoveFailed,
    DeploymentTrashNameTaken,
    EnabledFileChangeError,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification

DEFAULT_MUTEX_WAIT_SECONDS = 30.0


class _TrashMover(Protocol):
    def read_original(self, strategy_instance_id: str) -> bytes: ...

    def move_to_trash(self, strategy_instance_id: str, original: bytes) -> str: ...


class StrategyDeleteService:
    def __init__(
        self,
        *,
        load_snapshot: Callable[[], DeploymentCatalogSnapshot],
        trash_mover: _TrashMover,
        cancel_step: EntryOrderCancelStep,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        mutex_wait_seconds: float = DEFAULT_MUTEX_WAIT_SECONDS,
    ) -> None:
        self._load_snapshot = load_snapshot
        self._trash_mover = trash_mover
        self._cancel_step = cancel_step
        self._keyed_mutex_registry = keyed_mutex_registry
        self._mutex_wait_seconds = mutex_wait_seconds

    def delete(self, strategy_instance_id: str) -> DeleteResult:
        # An unknown id must not reach the mutex registry (it keeps one lock per key).
        self._deployment(strategy_instance_id)
        try:
            with self._keyed_mutex_registry.hold(
                strategy_instance_id, timeout_seconds=self._mutex_wait_seconds
            ):
                return self._delete_locked(strategy_instance_id)
        except StrategyInstanceBusy as exc:
            raise InstanceBusy from exc

    def _delete_locked(self, strategy_instance_id: str) -> DeleteResult:
        if self._deployment(strategy_instance_id).enabled:
            raise StillEnabled
        original = self._guard(lambda: self._trash_mover.read_original(strategy_instance_id))
        cancelled = self._cancel_step.run(strategy_instance_id)
        trash_file = self._guard(
            lambda: self._trash_mover.move_to_trash(strategy_instance_id, original)
        )
        return DeleteResult(strategy_instance_id, cancelled, trash_file)

    def _deployment(self, strategy_instance_id: str) -> DeploymentSpecification:
        try:
            snapshot = self._load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise CatalogUnavailable from exc
        deployment = snapshot.get_by_strategy_instance_id(strategy_instance_id)
        if deployment is None:
            raise StrategyInstanceNotFound
        return deployment

    @staticmethod
    def _guard[T](action: Callable[[], T]) -> T:
        try:
            return action()
        except DeploymentNotInCatalog as exc:
            raise StrategyInstanceNotFound from exc
        except DeploymentFileChanged as exc:
            raise FileChanged from exc
        except DeploymentTrashNameTaken as exc:
            raise TrashNameTaken from exc
        except DeploymentTrashMoveFailed as exc:
            raise MoveFailed from exc
        except EnabledFileChangeError as exc:
            raise MoveFailed from exc
