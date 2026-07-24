"""Startup filesystem preparation."""

from pathlib import Path


def prepare_journal_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise ValueError("RUNTIME_JOURNAL_PATH must identify a file")
    with path.open("a", encoding="utf-8"):
        pass


def prepare_specs_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("RUNTIME_SPECS_PATH must identify a directory")
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        raise ValueError("RUNTIME_SPECS_PATH must be readable") from exc
