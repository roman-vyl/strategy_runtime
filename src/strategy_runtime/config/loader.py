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

    return RuntimeConfig(
        host=values.get("RUNTIME_HOST", "127.0.0.1"),
        port=port,
        journal_path=Path(journal_text),
        specs_path=Path(specs_text),
        service_instance=values.get("RUNTIME_SERVICE_INSTANCE", "local"),
    )
