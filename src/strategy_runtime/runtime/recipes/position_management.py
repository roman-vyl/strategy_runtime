"""Immutable open-position management recipe models returned by Strategy Engine."""

from collections.abc import Mapping
from dataclasses import dataclass

from strategy_runtime.shared.decimal_text import normalize_decimal_text
from strategy_runtime.utility.deployment_catalog.models import FrozenJsonValue, freeze_json


@dataclass(frozen=True, slots=True)
class DesiredProtection:
    stop_price: str
    take_price: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop_price", normalize_decimal_text(self.stop_price))
        if self.take_price is not None:
            object.__setattr__(self, "take_price", normalize_decimal_text(self.take_price))


@dataclass(frozen=True, slots=True)
class CloseSignal:
    active: bool
    reason: str | None = None
    component_id: str | None = None
    layer: str | None = None


@dataclass(frozen=True, slots=True)
class PositionManagementRecipe:
    desired_protection: DesiredProtection
    close_signal: CloseSignal
    diagnostics: Mapping[str, FrozenJsonValue]

    def __post_init__(self) -> None:
        frozen = freeze_json(dict(self.diagnostics))
        if not isinstance(frozen, Mapping):
            raise TypeError("diagnostics must be an object")
        object.__setattr__(self, "diagnostics", frozen)
