"""`DeploymentEnabledFileWriter`: atomic single-field replacement of a deployment file."""

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from strategy_runtime.utility.deployment_catalog import (
    DeploymentEnabledFileWriter,
    DeploymentFileChanged,
    DeploymentFileWriteFailed,
    DeploymentNotInCatalog,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)
from strategy_runtime.utility.deployment_catalog import enabled_writer as writer_module

RAW_SPEC = {"anchor": 500, "nested": {"enabled": True, "levels": [1, 2.5, 1e-7]}}


def document(enabled: bool = True) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "ticker": "BTCUSDT.P",
        "base_timeframe": "5m",
        "strategy_id": "ema_pullback",
        "raw_spec": RAW_SPEC,
        "research_source": {"candidate_id": "cand_x", "note": "kept"},
    }


def spec_id() -> str:
    return derive_strategy_instance_id(
        strategy_id="ema_pullback",
        ticker="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec=RAW_SPEC,
    )


def write(directory: Path, name: str, text: str, mode: int = 0o644) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def make_writer(directory: Path) -> DeploymentEnabledFileWriter:
    return DeploymentEnabledFileWriter(FilesystemDeploymentCatalog(directory), directory)


def research_style(enabled: bool) -> str:
    return json.dumps(document(enabled), indent=1, sort_keys=False) + "\n"


def test_only_the_enabled_line_changes_and_format_and_mode_are_kept(tmp_path: Path) -> None:
    original = research_style(True)
    path = write(tmp_path, "a.json", original, mode=0o644)

    changed = make_writer(tmp_path).set_enabled(spec_id(), False)

    assert changed is True
    updated = path.read_text(encoding="utf-8")
    assert updated == research_style(False)
    assert updated.endswith("\n")
    old_lines, new_lines = original.splitlines(), updated.splitlines()
    assert [i for i, (a, b) in enumerate(zip(old_lines, new_lines, strict=True)) if a != b] == [1]
    assert len(old_lines) == len(new_lines)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert json.loads(updated)["research_source"] == {"candidate_id": "cand_x", "note": "kept"}


def test_identity_is_unchanged_and_nested_enabled_is_not_touched(tmp_path: Path) -> None:
    write(tmp_path, "a.json", research_style(False))

    make_writer(tmp_path).set_enabled(spec_id(), True)

    catalog = FilesystemDeploymentCatalog(tmp_path).load_snapshot()
    (item,) = catalog.accepted_deployments
    assert item.strategy_instance_id == spec_id()
    assert item.enabled is True
    assert dict(item.raw_spec)["nested"]["enabled"] is True  # type: ignore[index]


def test_file_without_trailing_newline_and_compact_file_keep_their_shape(tmp_path: Path) -> None:
    compact = json.dumps(document(True), separators=(", ", ": "))
    path = write(tmp_path, "a.json", compact)

    make_writer(tmp_path).set_enabled(spec_id(), False)

    updated = path.read_text(encoding="utf-8")
    assert "\n" not in updated
    assert json.loads(updated)["enabled"] is False


def test_already_in_requested_state_writes_nothing(tmp_path: Path) -> None:
    path = write(tmp_path, "a.json", research_style(False))
    before = path.stat()

    assert make_writer(tmp_path).set_enabled(spec_id(), False) is False

    assert path.read_text(encoding="utf-8") == research_style(False)
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_temporary_file_is_hidden_from_the_catalog_while_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "a.json", research_style(True))
    seen: list[tuple[str, ...]] = []
    real_replace = os.replace

    def spying_replace(source: Any, destination: Any) -> None:
        names = sorted(p.name for p in tmp_path.iterdir())
        assert any(name.startswith(".a.json.tmp-") for name in names)
        snapshot = FilesystemDeploymentCatalog(tmp_path).load_snapshot()
        seen.append(tuple(item.source_path for item in snapshot.accepted_deployments))
        real_replace(source, destination)

    monkeypatch.setattr(writer_module.os, "replace", spying_replace)

    make_writer(tmp_path).set_enabled(spec_id(), False)

    assert seen == [("a.json",)]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


def test_file_changed_between_read_and_replace_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "a.json", research_style(True))
    edited = research_style(True).replace("cand_x", "cand_hand_edited")
    real_open = os.open

    def editing_open(target: Any, flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(target, flags, mode)
        if str(target).startswith(str(tmp_path / ".a.json.tmp-")):
            path.write_text(edited, encoding="utf-8")  # a hand edit after the original was read
        return descriptor

    monkeypatch.setattr(writer_module.os, "open", editing_open)

    with pytest.raises(DeploymentFileChanged):
        make_writer(tmp_path).set_enabled(spec_id(), False)

    assert path.read_text(encoding="utf-8") == edited
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


def test_file_edited_after_the_snapshot_so_identity_differs_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "a.json", research_style(True))
    catalog = FilesystemDeploymentCatalog(tmp_path)
    original_load = catalog.load_snapshot

    def load_then_edit() -> Any:
        snapshot = original_load()
        edited = document(True)
        edited["raw_spec"] = {"anchor": 1000}
        path.write_text(json.dumps(edited), encoding="utf-8")
        return snapshot

    monkeypatch.setattr(catalog, "load_snapshot", load_then_edit)

    with pytest.raises(DeploymentFileChanged):
        DeploymentEnabledFileWriter(catalog, tmp_path).set_enabled(spec_id(), False)

    assert json.loads(path.read_text(encoding="utf-8"))["raw_spec"] == {"anchor": 1000}


def test_replace_failure_keeps_the_original_whole_and_removes_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "a.json", research_style(True))

    def failing_replace(source: Any, destination: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(writer_module.os, "replace", failing_replace)

    with pytest.raises(DeploymentFileWriteFailed):
        make_writer(tmp_path).set_enabled(spec_id(), False)

    assert path.read_text(encoding="utf-8") == research_style(True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


def test_temporary_write_failure_leaves_original_and_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "a.json", research_style(True))

    def failing_fsync(descriptor: int) -> None:
        raise OSError("io error")

    monkeypatch.setattr(writer_module.os, "fsync", failing_fsync)

    with pytest.raises(DeploymentFileWriteFailed):
        make_writer(tmp_path).set_enabled(spec_id(), False)

    assert path.read_text(encoding="utf-8") == research_style(True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


def test_unknown_duplicate_and_invalid_files_are_not_written(tmp_path: Path) -> None:
    write(tmp_path, "dup1.json", research_style(True))
    write(tmp_path, "dup2.json", research_style(True))
    write(tmp_path, "bad.json", "{not json")
    writer = make_writer(tmp_path)

    with pytest.raises(DeploymentNotInCatalog):
        writer.set_enabled(spec_id(), False)  # duplicate identity is excluded fail-closed
    with pytest.raises(DeploymentNotInCatalog):
        writer.set_enabled("ema_pullback:unknown", False)

    assert (tmp_path / "dup1.json").read_text(encoding="utf-8") == research_style(True)
    assert (tmp_path / "bad.json").read_text(encoding="utf-8") == "{not json"
