"""Managed change of the `enabled` field of one existing deployment file."""

import contextlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Protocol

from strategy_runtime.utility.deployment_catalog.errors import (
    DeploymentCatalogUnavailableError,
)
from strategy_runtime.utility.deployment_catalog.identity import (
    derive_strategy_instance_id,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentCatalogSnapshot

_LOGGER = logging.getLogger(__name__)


class _SnapshotSource(Protocol):
    def load_snapshot(self) -> DeploymentCatalogSnapshot: ...


class EnabledFileChangeError(RuntimeError):
    """The enabled change was refused; the original file is untouched and whole."""

    reason = "enabled_file_change_error"


class DeploymentNotInCatalog(EnabledFileChangeError):
    reason = "unknown_instance"


class DeploymentFileChanged(EnabledFileChangeError):
    reason = "file_changed"


class DeploymentIdentityWouldChange(EnabledFileChangeError):
    reason = "identity_changed"


class DeploymentFileWriteFailed(EnabledFileChangeError):
    reason = "write_failed"


class DeploymentEnabledFileWriter:
    """Replace one accepted deployment file atomically, changing only `enabled`.

    The new document equals the old one except for `enabled` (same keys, same order,
    same indentation and trailing newline, same file mode). It is written to a hidden
    temporary file in the same directory (the catalog ignores names starting with `.`),
    flushed, and moved over the original with `os.replace` after the original is read
    again and found byte-identical to what the change was built from.
    """

    def __init__(self, catalog: _SnapshotSource, catalog_path: Path) -> None:
        self._catalog = catalog
        self._catalog_path = catalog_path

    def set_enabled(self, strategy_instance_id: str, enabled: bool) -> bool:
        """Return True when the file was replaced, False when it already had the value."""
        try:
            snapshot = self._catalog.load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise DeploymentFileWriteFailed("deployment catalog is unavailable") from exc
        deployment = snapshot.get_by_strategy_instance_id(strategy_instance_id)
        if deployment is None:
            raise DeploymentNotInCatalog(strategy_instance_id)
        path = self._catalog_path / deployment.source_path

        try:
            original = path.read_bytes()
            mode = path.stat().st_mode & 0o777
        except OSError as exc:
            raise DeploymentFileWriteFailed(str(exc)) from exc
        document = _parse_document(original)
        if document is None or _identity_of(document) != strategy_instance_id:
            raise DeploymentFileChanged(strategy_instance_id)
        if document["enabled"] is enabled:
            return False

        updated = {**document, "enabled": enabled}
        if _identity_of(updated) != strategy_instance_id:
            raise DeploymentIdentityWouldChange(strategy_instance_id)
        payload = _serialize(updated, original)
        reparsed = _parse_document(payload)
        if (
            reparsed is None
            or reparsed != updated
            or _identity_of(reparsed) != strategy_instance_id
        ):
            raise DeploymentIdentityWouldChange(strategy_instance_id)

        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            self._write_temporary(temporary, payload, mode)
            try:
                current = path.read_bytes()
            except OSError as exc:
                raise DeploymentFileWriteFailed(str(exc)) from exc
            if current != original:
                raise DeploymentFileChanged(strategy_instance_id)
            try:
                os.replace(temporary, path)
            except OSError as exc:
                raise DeploymentFileWriteFailed(str(exc)) from exc
        except BaseException:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise
        self._sync_directory()
        return True

    @staticmethod
    def _write_temporary(temporary: Path, payload: bytes, mode: int) -> None:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.fchmod(descriptor, mode)
                view = memoryview(payload)
                while view:
                    view = view[os.write(descriptor, view) :]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise DeploymentFileWriteFailed(str(exc)) from exc

    def _sync_directory(self) -> None:
        # The file is replaced once `os.replace` returned; a failed directory sync only
        # weakens durability across a host crash.
        try:
            descriptor = os.open(self._catalog_path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            _LOGGER.warning("deployment directory sync failed after enabled change", exc_info=True)


def _reject_non_finite_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _parse_document(content: bytes) -> dict[str, Any] | None:
    try:
        document = json.loads(content.decode("utf-8"), parse_constant=_reject_non_finite_number)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict) or type(document.get("enabled")) is not bool:
        return None
    return document


def _identity_of(document: dict[str, Any]) -> str | None:
    try:
        return derive_strategy_instance_id(
            strategy_id=document["strategy_id"],
            ticker=document["ticker"],
            base_timeframe=document["base_timeframe"],
            raw_spec=document["raw_spec"],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _serialize(document: dict[str, Any], original: bytes) -> bytes:
    text = original.decode("utf-8")
    indent = _detect_indent(text)
    rendered = json.dumps(document, indent=indent, ensure_ascii=False, allow_nan=False)
    if text.endswith("\n"):
        rendered += "\n"
    return rendered.encode("utf-8")


def _detect_indent(text: str) -> int | None:
    lines = text.split("\n")
    if len(lines) < 2:
        return None
    for line in lines[1:]:
        stripped = line.lstrip(" ")
        if stripped and len(stripped) != len(line):
            return len(line) - len(stripped)
        if stripped:
            return None
    return None
