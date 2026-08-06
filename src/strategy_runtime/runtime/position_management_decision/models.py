"""Transport-free values used by the pure position-management decision."""

from dataclasses import dataclass

from strategy_runtime.runtime.recipes.position_management import CloseSignal, DesiredProtection


@dataclass(frozen=True, slots=True)
class NoOp:
    """No position-management execution action is required."""


@dataclass(frozen=True, slots=True)
class ApplyProtection:
    """Apply changed protection to the acknowledged current cycle."""

    trade_cycle_id: str
    desired_protection: DesiredProtection

    def __post_init__(self) -> None:
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_desired_protection(self.desired_protection, "desired_protection")


@dataclass(frozen=True, slots=True)
class ClosePosition:
    """Close the acknowledged current cycle's position."""

    trade_cycle_id: str
    close_signal: CloseSignal

    def __post_init__(self) -> None:
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        if type(self.close_signal) is not CloseSignal:
            raise TypeError("close_signal must be CloseSignal")


PositionManagementDecision = NoOp | ApplyProtection | ClosePosition


def _require_non_empty_string(value: str, name: str) -> None:
    if type(value) is not str or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty string")


def _require_desired_protection(value: DesiredProtection, name: str) -> None:
    if type(value) is not DesiredProtection:
        raise TypeError(f"{name} must be DesiredProtection")
