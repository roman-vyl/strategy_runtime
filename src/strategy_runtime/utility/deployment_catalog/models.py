"""Immutable deployment-catalog domain models."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

type JsonScalar = str | int | float | bool | None
type FrozenJsonValue = JsonScalar | tuple["FrozenJsonValue", ...] | Mapping[str, "FrozenJsonValue"]


def freeze_json(value: Any) -> FrozenJsonValue:
    """Return a detached, recursively immutable JSON-compatible value."""

    if isinstance(value, Mapping):
        frozen = {str(key): freeze_json(item) for key, item in value.items()}
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("raw_spec contains a non-JSON-compatible value")


@dataclass(frozen=True, slots=True)
class DeploymentSpecification:
    """One accepted immutable strategy deployment specification."""

    strategy_instance_id: str
    enabled: bool
    instrument: str
    base_timeframe: str
    strategy_id: str
    raw_spec: Mapping[str, FrozenJsonValue]
    source_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        for field_name in (
            "strategy_instance_id",
            "instrument",
            "base_timeframe",
            "strategy_id",
            "source_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.raw_spec, Mapping):
            raise TypeError("raw_spec must be an object")
        frozen = freeze_json(self.raw_spec)
        if not isinstance(frozen, Mapping):
            raise TypeError("raw_spec must be an object")
        object.__setattr__(self, "raw_spec", frozen)


@dataclass(frozen=True, slots=True)
class InvalidDeploymentFile:
    source_path: str
    error_code: str
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateDeploymentIdentity:
    strategy_instance_id: str
    source_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeploymentCatalogSnapshot:
    scanned_file_count: int
    accepted_deployments: tuple[DeploymentSpecification, ...]
    invalid_files: tuple[InvalidDeploymentFile, ...]
    duplicate_identities: tuple[DuplicateDeploymentIdentity, ...]
    _by_strategy_instance_id: Mapping[str, DeploymentSpecification] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.scanned_file_count < 0:
            raise ValueError("scanned_file_count must be non-negative")
        index = {
            deployment.strategy_instance_id: deployment for deployment in self.accepted_deployments
        }
        if len(index) != len(self.accepted_deployments):
            raise ValueError("accepted deployments must have unique stable identities")
        object.__setattr__(
            self,
            "_by_strategy_instance_id",
            MappingProxyType(index),
        )

    def get_by_strategy_instance_id(
        self, strategy_instance_id: str
    ) -> DeploymentSpecification | None:
        """Return one exact accepted deployment identity, if present."""

        return self._by_strategy_instance_id.get(strategy_instance_id)
