"""Transport-free DTOs for the ABI entry-cycle recovery-state contract."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from strategy_runtime.runtime.abi.entry_package_models import EntryPackageWireDesiredEntry
from strategy_runtime.shared.decimal_text import (
    is_exact_decimal_text,
    is_positive_exact_decimal_text,
)


@dataclass(frozen=True, slots=True)
class RecoveryStateAppliedEntryPackage:
    """The applied entry package ABI durably holds for a live order or open position."""

    applied_desired_entry: EntryPackageWireDesiredEntry
    calculated_quantity: str

    def __post_init__(self) -> None:
        if type(self.applied_desired_entry) is not EntryPackageWireDesiredEntry:
            raise TypeError("applied_desired_entry must be EntryPackageWireDesiredEntry")
        if not is_exact_decimal_text(self.calculated_quantity):
            raise ValueError("calculated_quantity must be exact-decimal text")


@dataclass(frozen=True, slots=True)
class EntryOrderLiveRecoveryState:
    """ABI positively established a live, unfilled entry order."""

    applied_entry_package: RecoveryStateAppliedEntryPackage

    kind: ClassVar[Literal["entry_order_live"]] = "entry_order_live"

    def __post_init__(self) -> None:
        if type(self.applied_entry_package) is not RecoveryStateAppliedEntryPackage:
            raise TypeError("applied_entry_package must be RecoveryStateAppliedEntryPackage")


@dataclass(frozen=True, slots=True)
class EntryOrderNotFoundRecoveryState:
    """ABI's fresh, non-terminal ambiguous-CREATE absence observation."""

    kind: ClassVar[Literal["entry_order_not_found"]] = "entry_order_not_found"


@dataclass(frozen=True, slots=True)
class PositionOpenRecoveryState:
    """ABI positively established a filled, open position."""

    applied_entry_package: RecoveryStateAppliedEntryPackage
    first_fill_at_ms: int
    average_entry_price: str

    kind: ClassVar[Literal["position_open"]] = "position_open"

    def __post_init__(self) -> None:
        if type(self.applied_entry_package) is not RecoveryStateAppliedEntryPackage:
            raise TypeError("applied_entry_package must be RecoveryStateAppliedEntryPackage")
        if type(self.first_fill_at_ms) is not int or self.first_fill_at_ms <= 0:
            raise ValueError("first_fill_at_ms must be a strictly positive integer")
        if not is_positive_exact_decimal_text(self.average_entry_price):
            raise ValueError("average_entry_price must be positive exact-decimal text")


@dataclass(frozen=True, slots=True)
class TerminalWithoutFillRecoveryState:
    """ABI positively established a terminal outcome that never filled."""

    kind: ClassVar[Literal["terminal_without_fill"]] = "terminal_without_fill"


@dataclass(frozen=True, slots=True)
class TerminalAfterFillRecoveryState:
    """ABI positively established a fill whose position has since fully closed."""

    kind: ClassVar[Literal["terminal_after_fill"]] = "terminal_after_fill"


RecoveryStateResponse = (
    EntryOrderLiveRecoveryState
    | EntryOrderNotFoundRecoveryState
    | PositionOpenRecoveryState
    | TerminalWithoutFillRecoveryState
    | TerminalAfterFillRecoveryState
)
