from pathlib import Path

import pytest

from strategy_runtime.config.loader import load_runtime_config
from strategy_runtime.config.model import RuntimeConfig
from strategy_runtime.config.startup import prepare_journal_path, prepare_specs_path

_REQUIRED_OUTBOUND_ENV = {
    "RUNTIME_STRATEGY_ENGINE_BASE_URL": "http://engine.internal",
    "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS": "5",
    "RUNTIME_ABI_BASE_URL": "http://abi.internal",
    "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS": "5",
    "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS": "5",
    "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": "256",
}


def test_loads_defaults() -> None:
    config = load_runtime_config(dict(_REQUIRED_OUTBOUND_ENV))
    assert config.host == "127.0.0.1"
    assert config.port == 8093
    assert config.journal_path == Path("var/journal/runtime.jsonl")
    assert config.specs_path == Path("var/specs")
    assert config.service_instance == "local"


def test_environment_overrides() -> None:
    config = load_runtime_config(
        {
            **_REQUIRED_OUTBOUND_ENV,
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


def test_loads_required_outbound_fields() -> None:
    config = load_runtime_config(dict(_REQUIRED_OUTBOUND_ENV))
    assert config.strategy_engine_base_url == "http://engine.internal"
    assert config.strategy_engine_timeout_seconds == 5.0
    assert config.abi_base_url == "http://abi.internal"
    assert config.abi_open_position_timeout_seconds == 5.0
    assert config.abi_entry_package_timeout_seconds == 5.0
    assert config.committed_bar_queue_capacity == 256


@pytest.mark.parametrize(
    "missing",
    [
        "RUNTIME_STRATEGY_ENGINE_BASE_URL",
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS",
        "RUNTIME_ABI_BASE_URL",
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS",
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS",
        "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY",
    ],
)
def test_rejects_missing_required_outbound_field(missing: str) -> None:
    env = dict(_REQUIRED_OUTBOUND_ENV)
    del env[missing]
    with pytest.raises(ValueError):
        load_runtime_config(env)


@pytest.mark.parametrize(
    "name",
    [
        "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS",
        "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS",
        "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS",
    ],
)
def test_rejects_unparsable_outbound_timeout(name: str) -> None:
    env = {**_REQUIRED_OUTBOUND_ENV, name: "not-a-number"}
    with pytest.raises(ValueError):
        load_runtime_config(env)


@pytest.mark.parametrize("value", ["", "   ", "not-an-integer", "1.5"])
def test_rejects_unparsable_committed_bar_queue_capacity(value: str) -> None:
    env = {**_REQUIRED_OUTBOUND_ENV, "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": value}
    with pytest.raises(ValueError):
        load_runtime_config(env)


@pytest.mark.parametrize("value", ["0", "-1", "-256"])
def test_rejects_non_positive_committed_bar_queue_capacity(value: str) -> None:
    env = {**_REQUIRED_OUTBOUND_ENV, "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY": value}
    with pytest.raises(ValueError):
        load_runtime_config(env)


def test_committed_bar_queue_capacity_missing_fails_before_any_outbound_client_is_needed() -> None:
    env = dict(_REQUIRED_OUTBOUND_ENV)
    del env["RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY"]
    with pytest.raises(ValueError, match="RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY"):
        load_runtime_config(env)


@pytest.mark.parametrize("capacity", [0, -1])
def test_runtime_config_post_init_rejects_non_positive_committed_bar_queue_capacity(
    capacity: int,
) -> None:
    with pytest.raises(ValueError):
        RuntimeConfig(
            strategy_engine_base_url="http://engine.internal",
            strategy_engine_timeout_seconds=5.0,
            abi_base_url="http://abi.internal",
            abi_open_position_timeout_seconds=5.0,
            abi_entry_package_timeout_seconds=5.0,
            committed_bar_queue_capacity=capacity,
        )


@pytest.mark.parametrize(
    "name",
    ["RUNTIME_STRATEGY_ENGINE_BASE_URL", "RUNTIME_ABI_BASE_URL"],
)
def test_rejects_empty_outbound_base_url(name: str) -> None:
    env = {**_REQUIRED_OUTBOUND_ENV, name: "  "}
    with pytest.raises(ValueError):
        load_runtime_config(env)


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
