"""Environment-backed Runtime configuration loader."""

import os
from collections.abc import Mapping
from pathlib import Path

from strategy_runtime.config.model import RuntimeConfig


def load_runtime_config(environ: Mapping[str, str] | None = None) -> RuntimeConfig:
    values = os.environ if environ is None else environ
    port_text = values.get("RUNTIME_PORT", "8093")
    journal_text = values.get("RUNTIME_JOURNAL_PATH", "var/journal/runtime.jsonl")
    specs_text = values.get("RUNTIME_SPECS_PATH", "var/specs")
    if not journal_text.strip():
        raise ValueError("RUNTIME_JOURNAL_PATH must not be empty")
    if not specs_text.strip():
        raise ValueError("RUNTIME_SPECS_PATH must not be empty")
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

    return RuntimeConfig(
        host=values.get("RUNTIME_HOST", "127.0.0.1"),
        port=port,
        journal_path=Path(journal_text),
        specs_path=Path(specs_text),
        strategy_engine_base_url=strategy_engine_base_url,
        strategy_engine_timeout_seconds=strategy_engine_timeout_seconds,
        abi_base_url=abi_base_url,
        abi_open_position_timeout_seconds=abi_open_position_timeout_seconds,
        abi_entry_package_timeout_seconds=abi_entry_package_timeout_seconds,
        abi_position_management_timeout_seconds=abi_position_management_timeout_seconds,
        committed_bar_queue_capacity=committed_bar_queue_capacity,
    )


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
