"""Immutable event models for committed-bar processing observability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonValue, ...] | Mapping[str, JsonValue]


class ProcessingJournalEventType(StrEnum):
    COMMITTED_BAR_ORCHESTRATION_STARTED = "committed_bar_orchestration_started"
    COMMITTED_BAR_ORCHESTRATION_FAILED = "committed_bar_orchestration_failed"
    STRATEGY_CYCLE_DISPATCH_SUCCEEDED = "strategy_cycle_dispatch_succeeded"
    STRATEGY_CYCLE_DISPATCH_FAILED = "strategy_cycle_dispatch_failed"
    COMMITTED_BAR_ORCHESTRATION_COMPLETED = "committed_bar_orchestration_completed"


def freeze_json(value: object) -> JsonValue:
    """Return a recursively immutable JSON-safe value."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        frozen = {str(key): freeze_json(item) for key, item in value.items()}
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"value is not JSON-safe: {type(value).__name__}")


def thaw_json(value: JsonValue) -> object:
    """Convert an immutable JSON value into serializer-friendly containers."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ProcessingJournalEvent:
    schema_version: int
    event_id: str
    event_type: ProcessingJournalEventType
    occurred_at: str
    source: str
    severity: str
    payload: Mapping[str, JsonValue]
    diagnostics: Mapping[str, JsonValue]
    strategy_instance_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        for name, value in (
            ("event_id", self.event_id),
            ("occurred_at", self.occurred_at),
            ("source", self.source),
            ("severity", self.severity),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.strategy_instance_id is not None and not self.strategy_instance_id.strip():
            raise ValueError("strategy_instance_id must be non-empty when supplied")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "diagnostics", freeze_json(self.diagnostics))

    def to_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at,
            "source": self.source,
            "severity": self.severity,
            "payload": thaw_json(self.payload),
            "diagnostics": thaw_json(self.diagnostics),
        }
        if self.strategy_instance_id is not None:
            record["strategy_instance_id"] = self.strategy_instance_id
        return record
