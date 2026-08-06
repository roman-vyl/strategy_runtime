"""Transport-free commands and confirmations for position-management execution."""

from dataclasses import dataclass

from strategy_runtime.runtime.recipes.position_management import DesiredProtection


@dataclass(frozen=True, slots=True)
class ApplyProtectionCommand:
    """Runtime-issued instruction to apply the desired protection to a trade cycle."""

    strategy_instance_id: str
    trade_cycle_id: str
    desired_protection: DesiredProtection

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_desired_protection(self.desired_protection, "desired_protection")


@dataclass(frozen=True, slots=True)
class ClosePositionCommand:
    """Runtime-issued instruction to close the entire current position."""

    strategy_instance_id: str
    trade_cycle_id: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")


@dataclass(frozen=True, slots=True)
class ProtectionAppliedConfirmation:
    """The executor's verified confirmation that the requested protection is applied."""

    strategy_instance_id: str
    trade_cycle_id: str
    confirmed_protection: DesiredProtection

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_desired_protection(self.confirmed_protection, "confirmed_protection")


@dataclass(frozen=True, slots=True)
class PositionClosedConfirmation:
    """The executor's verified confirmation that no open position remainder exists."""

    strategy_instance_id: str
    trade_cycle_id: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")


PositionManagementExecutionCommand = ApplyProtectionCommand | ClosePositionCommand
PositionManagementExecutionConfirmation = ProtectionAppliedConfirmation | PositionClosedConfirmation


def _require_non_empty_string(value: str, name: str) -> None:
    if type(value) is not str or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty string")


def _require_desired_protection(value: DesiredProtection, name: str) -> None:
    if type(value) is not DesiredProtection:
        raise TypeError(f"{name} must be DesiredProtection")
