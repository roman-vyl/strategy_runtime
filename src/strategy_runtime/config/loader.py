"""Environment-backed Runtime configuration loader."""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from strategy_runtime.config.model import LIVE_ENTRY_MODES, LiveEntryMode, RuntimeConfig

_CONFIG_FILE_KEYS = frozenset({"live_entry_mode", "order_lifetime_bars"})


def load_runtime_config(environ: Mapping[str, str] | None = None) -> RuntimeConfig:
    values = os.environ if environ is None else environ
    port_text = values.get("RUNTIME_PORT", "8093")
    journal_text = values.get("RUNTIME_JOURNAL_PATH", "var/journal/runtime.jsonl")
    specs_text = values.get("RUNTIME_SPECS_PATH", "var/specs")
    state_text = values.get("RUNTIME_STATE_PATH", "var/state/runtime_state.jsonl")
    if not journal_text.strip():
        raise ValueError("RUNTIME_JOURNAL_PATH must not be empty")
    if not specs_text.strip():
        raise ValueError("RUNTIME_SPECS_PATH must not be empty")
    if not state_text.strip():
        raise ValueError("RUNTIME_STATE_PATH must not be empty")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("RUNTIME_PORT must be an integer") from exc

    strategy_engine_base_url = _require_text(values, "RUNTIME_STRATEGY_ENGINE_BASE_URL")
    strategy_engine_timeout_seconds = _require_float(
        values, "RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS"
    )
    abi_base_url = _require_text(values, "RUNTIME_ABI_BASE_URL")
    abi_open_position_timeout_seconds = _require_float(
        values, "RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS"
    )
    abi_entry_package_timeout_seconds = _require_float(
        values, "RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS"
    )
    abi_position_management_timeout_seconds = _require_float(
        values, "RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS"
    )
    committed_bar_queue_capacity = _require_int(values, "RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY")
    config_file = _read_config_file(values.get("RUNTIME_CONFIG_PATH", ""))

    return RuntimeConfig(
        host=values.get("RUNTIME_HOST", "127.0.0.1"),
        port=port,
        journal_path=Path(journal_text),
        specs_path=Path(specs_text),
        state_path=Path(state_text),
        strategy_engine_base_url=strategy_engine_base_url,
        strategy_engine_timeout_seconds=strategy_engine_timeout_seconds,
        abi_base_url=abi_base_url,
        abi_open_position_timeout_seconds=abi_open_position_timeout_seconds,
        abi_entry_package_timeout_seconds=abi_entry_package_timeout_seconds,
        abi_position_management_timeout_seconds=abi_position_management_timeout_seconds,
        committed_bar_queue_capacity=committed_bar_queue_capacity,
        live_entry_mode=_live_entry_mode(config_file),
        order_lifetime_bars=_order_lifetime_bars(config_file),
    )


def _read_config_file(path_text: str) -> dict[str, Any]:
    """Read the optional TOML config file once; unset path or missing file means defaults."""
    if not path_text.strip():
        return {}
    path = Path(path_text)
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"RUNTIME_CONFIG_PATH file {path} is not valid TOML: {exc}") from exc
    unknown = sorted(set(data) - _CONFIG_FILE_KEYS)
    if unknown:
        raise ValueError(f"RUNTIME_CONFIG_PATH file {path} has unknown keys: {', '.join(unknown)}")
    return data


def _live_entry_mode(config: Mapping[str, Any]) -> LiveEntryMode:
    value = config.get("live_entry_mode", "ema_anchor")
    if value not in LIVE_ENTRY_MODES:
        raise ValueError(f"live_entry_mode must be one of {', '.join(LIVE_ENTRY_MODES)}")
    return cast(LiveEntryMode, value)


def _order_lifetime_bars(config: Mapping[str, Any]) -> int | None:
    value = config.get("order_lifetime_bars")
    if value is None:
        return None
    # TOML gives int, float, bool or str; only a non-negative int is a bar count.
    if type(value) is not int or value < 0:
        raise ValueError("order_lifetime_bars must be an integer >= 0")
    return value


def _require_text(values: Mapping[str, str], name: str) -> str:
    text = values.get(name)
    if text is None or not text.strip():
        raise ValueError(f"{name} must be set")
    return text


def _require_float(values: Mapping[str, str], name: str) -> float:
    text = values.get(name)
    if text is None or not text.strip():
        raise ValueError(f"{name} must be set")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _require_int(values: Mapping[str, str], name: str) -> int:
    text = values.get(name)
    if text is None or not text.strip():
        raise ValueError(f"{name} must be set")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
