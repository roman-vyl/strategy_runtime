"""Move one accepted deployment file into the hidden trash directory of the catalog."""

import contextlib
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from strategy_runtime.utility.deployment_catalog.enabled_writer import (
    DeploymentFileChanged,
    DeploymentNotInCatalog,
    EnabledFileChangeError,
)
from strategy_runtime.utility.deployment_catalog.errors import (
    DeploymentCatalogUnavailableError,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentCatalogSnapshot

_LOGGER = logging.getLogger(__name__)

TRASH_DIRECTORY_NAME = ".deleted"


class _SnapshotSource(Protocol):
    def load_snapshot(self) -> DeploymentCatalogSnapshot: ...


class DeploymentTrashNameTaken(EnabledFileChangeError):
    reason = "trash_name_taken"


class DeploymentTrashMoveFailed(EnabledFileChangeError):
    reason = "move_failed"


class DeploymentTrashMover:
    """Move a deployment file to `<catalog>/.deleted/<stem>.<UTC time>.json`, never erasing it.

    The catalog (and Research) list only top-level `*.json` files whose names do not start
    with `.`, so neither the subdirectory nor the files in it are ever listed. The move is a
    hard link into the trash followed by unlinking the original, which cannot overwrite.
    """

    def __init__(
        self,
        catalog: _SnapshotSource,
        catalog_path: Path,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._catalog = catalog
        self._catalog_path = catalog_path
        self._now = now

    def read_original(self, strategy_instance_id: str) -> bytes:
        return self._path_of(strategy_instance_id).read_bytes_checked()

    def move_to_trash(self, strategy_instance_id: str, original: bytes) -> str:
        """Move the file if it still holds `original`; return the trash path under the catalog."""
        path = self._path_of(strategy_instance_id).path
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise DeploymentTrashMoveFailed(str(exc)) from exc
        if current != original:
            raise DeploymentFileChanged(strategy_instance_id)

        trash = self._catalog_path / TRASH_DIRECTORY_NAME
        try:
            trash.mkdir(mode=0o755, exist_ok=True)
        except OSError as exc:
            raise DeploymentTrashMoveFailed(str(exc)) from exc
        target = trash / f"{path.stem}.{self._now().strftime('%Y%m%dT%H%M%SZ')}.json"
        try:
            os.link(path, target)
        except FileExistsError as exc:
            raise DeploymentTrashNameTaken(target.name) from exc
        except OSError as exc:
            raise DeploymentTrashMoveFailed(str(exc)) from exc
        try:
            if target.read_bytes() != original:
                # the file was replaced between the check and the link: keep it where it is
                target.unlink()
                raise DeploymentFileChanged(strategy_instance_id)
            os.unlink(path)
        except DeploymentFileChanged:
            raise
        except OSError as exc:
            with contextlib.suppress(OSError):
                target.unlink()
            raise DeploymentTrashMoveFailed(str(exc)) from exc
        self._sync_directory(trash)
        self._sync_directory(self._catalog_path)
        return f"{TRASH_DIRECTORY_NAME}/{target.name}"

    def _path_of(self, strategy_instance_id: str) -> "_Located":
        try:
            snapshot = self._catalog.load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise DeploymentTrashMoveFailed("deployment catalog is unavailable") from exc
        deployment = snapshot.get_by_strategy_instance_id(strategy_instance_id)
        if deployment is None:
            raise DeploymentNotInCatalog(strategy_instance_id)
        return _Located(self._catalog_path / deployment.source_path)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        # The move is done once the original is unlinked; a failed directory sync only
        # weakens durability across a host crash.
        try:
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            _LOGGER.warning("deployment directory sync failed after trash move", exc_info=True)


class _Located:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_bytes_checked(self) -> bytes:
        try:
            return self.path.read_bytes()
        except OSError as exc:
            raise DeploymentTrashMoveFailed(str(exc)) from exc
