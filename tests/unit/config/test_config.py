from pathlib import Path

import pytest

from strategy_runtime.config.loader import load_runtime_config
from strategy_runtime.config.startup import prepare_journal_path, prepare_specs_path


def test_loads_defaults() -> None:
    config = load_runtime_config({})
    assert config.host == "127.0.0.1"
    assert config.port == 8093
    assert config.journal_path == Path("var/journal/runtime.jsonl")
    assert config.specs_path == Path("var/specs")
    assert config.service_instance == "local"


def test_environment_overrides() -> None:
    config = load_runtime_config(
        {
            "RUNTIME_HOST": "0.0.0.0",
            "RUNTIME_PORT": "9000",
            "RUNTIME_JOURNAL_PATH": "tmp/events.jsonl",
            "RUNTIME_SERVICE_INSTANCE": "node-a",
            "RUNTIME_SPECS_PATH": "tmp/specs",
        }
    )
    assert config.port == 9000
    assert config.service_instance == "node-a"
    assert config.specs_path == Path("tmp/specs")


@pytest.mark.parametrize("port", ["abc", "0", "65536"])
def test_rejects_invalid_port(port: str) -> None:
    with pytest.raises(ValueError):
        load_runtime_config({"RUNTIME_PORT": port})


def test_rejects_empty_journal_path() -> None:
    with pytest.raises(ValueError):
        load_runtime_config({"RUNTIME_JOURNAL_PATH": " "})


def test_prepare_journal_path_preserves_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "runtime.jsonl"
    path.parent.mkdir()
    path.write_text("existing\n", encoding="utf-8")
    prepare_journal_path(path)
    assert path.read_text(encoding="utf-8") == "existing\n"


def test_rejects_empty_specs_path() -> None:
    with pytest.raises(ValueError):
        load_runtime_config({"RUNTIME_SPECS_PATH": " "})


def test_prepare_specs_path_creates_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "specs"
    prepare_specs_path(path)
    assert path.is_dir()
