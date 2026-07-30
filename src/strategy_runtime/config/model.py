"""Immutable Runtime configuration."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 8093
    journal_path: Path = Path("var/journal/runtime.jsonl")
    specs_path: Path = Path("var/specs")
    service_instance: str = "local"
    # The five fields below have no meaningful default: `load_runtime_config`
    # always requires their environment variables and never falls back to
    # the placeholder values here. The placeholders exist only so this
    # frozen dataclass remains constructible with keyword defaults; URL
    # shape and timeout sign/finiteness are validated by the outbound HTTP
    # adapter constructors, not here (see runtime-production-composition).
    strategy_engine_base_url: str = ""
    strategy_engine_timeout_seconds: float = 0.0
    abi_base_url: str = ""
    abi_open_position_timeout_seconds: float = 0.0
    abi_entry_package_timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("RUNTIME_HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("RUNTIME_PORT must be between 1 and 65535")
        if not str(self.journal_path).strip():
            raise ValueError("RUNTIME_JOURNAL_PATH must not be empty")
        if not str(self.specs_path).strip():
            raise ValueError("RUNTIME_SPECS_PATH must not be empty")
        if not self.service_instance.strip():
            raise ValueError("RUNTIME_SERVICE_INSTANCE must not be empty")
