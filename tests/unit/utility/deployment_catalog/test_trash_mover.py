"""`DeploymentTrashMover`: move a deployment file into the hidden trash, never erase it."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from strategy_runtime.utility.deployment_catalog import (
    TRASH_DIRECTORY_NAME,
    DeploymentFileChanged,
    DeploymentNotInCatalog,
    DeploymentTrashMoveFailed,
    DeploymentTrashMover,
    DeploymentTrashNameTaken,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

RAW_SPEC = {"anchor": 500}
SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec=RAW_SPEC
)
NOW = datetime(2026, 10, 22, 16, 5, 9, tzinfo=UTC)


def document() -> dict[str, Any]:
    return {
        "enabled": False,
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "strategy_id": "ema_pullback",
        "raw_spec": RAW_SPEC,
    }


def make(tmp_path: Path) -> tuple[DeploymentTrashMover, FilesystemDeploymentCatalog, Path]:
    path = tmp_path / "a.json"
    path.write_text(json.dumps(document(), indent=1) + "\n", encoding="utf-8")
    catalog = FilesystemDeploymentCatalog(tmp_path)
    return DeploymentTrashMover(catalog, tmp_path, now=lambda: NOW), catalog, path


def test_file_lands_in_the_trash_with_its_bytes_and_leaves_the_catalog(tmp_path: Path) -> None:
    mover, catalog, path = make(tmp_path)
    original = mover.read_original(SID)

    trash_file = mover.move_to_trash(SID, original)

    assert trash_file == f"{TRASH_DIRECTORY_NAME}/a.20261022T160509Z.json"
    assert (tmp_path / trash_file).read_bytes() == original
    assert not path.exists()
    snapshot = catalog.load_snapshot()
    assert snapshot.get_by_strategy_instance_id(SID) is None
    # neither the directory nor the file in it is a catalog entry or an invalid file
    assert snapshot.scanned_file_count == 0 and snapshot.invalid_files == ()


def test_moving_the_file_back_lists_it_again(tmp_path: Path) -> None:
    mover, catalog, path = make(tmp_path)
    trash_file = mover.move_to_trash(SID, mover.read_original(SID))

    os.replace(tmp_path / trash_file, path)

    assert catalog.load_snapshot().get_by_strategy_instance_id(SID) is not None


def test_file_changed_since_it_was_read_is_refused_and_nothing_moves(tmp_path: Path) -> None:
    mover, _, path = make(tmp_path)
    original = mover.read_original(SID)
    changed = path.read_bytes().replace(b"false", b"true")
    path.write_bytes(changed)

    with pytest.raises(DeploymentFileChanged):
        mover.move_to_trash(SID, original)

    assert path.read_bytes() == changed
    assert not (tmp_path / TRASH_DIRECTORY_NAME).exists() or not list(
        (tmp_path / TRASH_DIRECTORY_NAME).iterdir()
    )


def test_taken_trash_name_is_refused_and_both_files_stay_whole(tmp_path: Path) -> None:
    mover, _, path = make(tmp_path)
    original = mover.read_original(SID)
    trash = tmp_path / TRASH_DIRECTORY_NAME
    trash.mkdir()
    taken = trash / "a.20261022T160509Z.json"
    taken.write_text("earlier", encoding="utf-8")

    with pytest.raises(DeploymentTrashNameTaken):
        mover.move_to_trash(SID, original)

    assert path.read_bytes() == original
    assert taken.read_text(encoding="utf-8") == "earlier"


def test_failure_to_remove_the_original_removes_the_trash_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mover, _, path = make(tmp_path)
    original = mover.read_original(SID)

    real_unlink = os.unlink

    def unlink_fails(target: Any, *args: Any, **kwargs: Any) -> None:
        if Path(target) == path:
            raise OSError("read-only")
        real_unlink(target, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink_fails)
    with pytest.raises(DeploymentTrashMoveFailed):
        mover.move_to_trash(SID, original)
    monkeypatch.undo()

    assert path.read_bytes() == original
    assert list((tmp_path / TRASH_DIRECTORY_NAME).iterdir()) == []


def test_trash_directory_that_cannot_be_created_fails_and_keeps_the_file(tmp_path: Path) -> None:
    mover, _, path = make(tmp_path)
    original = mover.read_original(SID)
    (tmp_path / TRASH_DIRECTORY_NAME).write_text("not a directory", encoding="utf-8")

    with pytest.raises(DeploymentTrashMoveFailed):
        mover.move_to_trash(SID, original)

    assert path.read_bytes() == original


def test_unknown_instance_is_not_in_the_catalog(tmp_path: Path) -> None:
    mover, _, _ = make(tmp_path)

    with pytest.raises(DeploymentNotInCatalog):
        mover.read_original("ema_pullback:" + "0" * 24)
