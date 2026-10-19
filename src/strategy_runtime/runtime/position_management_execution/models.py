"""Transport-free commands and confirmations for position-management execution."""

from dataclasses import dataclass

from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
from strategy_runtime.shared.decimal_text import is_positive_exact_decimal_text


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


CANONICAL_CLOSE_EXPOSURE_FRACTION = "1"


@dataclass(frozen=True, slots=True)
class ClosePositionCommand:
    """Runtime-issued instruction to close the entire current position.

    V1 supports only the canonical full close: `exposure_fraction` must be exactly
    `"1"`, exact-decimal text. No arbitrary partial close.
    """

    strategy_instance_id: str
    trade_cycle_id: str
    exposure_fraction: str = CANONICAL_CLOSE_EXPOSURE_FRACTION

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        if self.exposure_fraction != CANONICAL_CLOSE_EXPOSURE_FRACTION:
            raise ValueError(
                "exposure_fraction must be the canonical value "
                f'"{CANONICAL_CLOSE_EXPOSURE_FRACTION}"'
            )


@dataclass(frozen=True, slots=True)
class ProtectionOrder:
    """One native protective order as ABI read it back: exchange text, unchanged."""

    order_id: str
    trigger_price: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.order_id, "order_id")
        _require_positive_exact_decimal_text(self.trigger_price, "trigger_price")


@dataclass(frozen=True, slots=True)
class ProtectionOrders:
    """The protective orders that carry a confirmed protection on the exchange.

    `quantity` is the cycle's position quantity both legs protect. `take` is
    always present: with no requested take it is ABI's surrogate take order.
    """

    quantity: str
    stop: ProtectionOrder
    take: ProtectionOrder

    def __post_init__(self) -> None:
        _require_positive_exact_decimal_text(self.quantity, "quantity")
        if type(self.stop) is not ProtectionOrder:
            raise TypeError("stop must be ProtectionOrder")
        if type(self.take) is not ProtectionOrder:
            raise TypeError("take must be ProtectionOrder")


@dataclass(frozen=True, slots=True)
class ProtectionAppliedConfirmation:
    """The executor's verified confirmation that the requested protection is applied.

    `protection_orders` is transient, for the `protection_applied` journal
    record only: never compared with the command, persisted or used in a decision.
    """

    strategy_instance_id: str
    trade_cycle_id: str
    confirmed_protection: DesiredProtection
    protection_orders: ProtectionOrders

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_desired_protection(self.confirmed_protection, "confirmed_protection")
        if type(self.protection_orders) is not ProtectionOrders:
            raise TypeError("protection_orders must be ProtectionOrders")


@dataclass(frozen=True, slots=True)
class PositionClosedConfirmation:
    """The executor's verified confirmation that no open position remainder exists."""

    strategy_instance_id: str
    trade_cycle_id: str
    closure: TradeCycleClosure | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        if self.closure is not None:
            if type(self.closure) is not TradeCycleClosure:
                raise TypeError("closure must be TradeCycleClosure or None")
            if (
                self.closure.strategy_instance_id != self.strategy_instance_id
                or self.closure.trade_cycle_id != self.trade_cycle_id
            ):
                raise ValueError("closure identity does not match the confirmation")


PositionManagementExecutionCommand = ApplyProtectionCommand | ClosePositionCommand
PositionManagementExecutionConfirmation = ProtectionAppliedConfirmation | PositionClosedConfirmation


def _require_non_empty_string(value: str, name: str) -> None:
    if type(value) is not str or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty string")


def _require_positive_exact_decimal_text(value: str, name: str) -> None:
    if type(value) is not str or not is_positive_exact_decimal_text(value):
        raise ValueError(f"{name} must be positive exact-decimal text")


def _require_desired_protection(value: DesiredProtection, name: str) -> None:
    if type(value) is not DesiredProtection:
        raise TypeError(f"{name} must be DesiredProtection")
