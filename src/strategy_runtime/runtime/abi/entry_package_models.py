"""Transport-free DTOs for the ABI desired-entry-package contract."""

from dataclasses import dataclass
from typing import ClassVar, Literal


def is_exact_decimal_text(value: str) -> bool:
    """Return whether value uses the finite exact-decimal grammar accepted by ABI."""
    valid, _ = _analyze_exact_decimal_text(value)
    return valid


def is_positive_exact_decimal_text(value: str) -> bool:
    """Return whether value is valid exact-decimal text representing a positive value."""
    valid, positive = _analyze_exact_decimal_text(value)
    return valid and positive


@dataclass(frozen=True, slots=True)
class EntryPackageWireDesiredEntry:
    """The exact ABI-facing DesiredEntry shape, without richer domain constraints."""

    side: Literal["long", "short"]
    source_plan_bar_open_time_ms: int
    planned_entry_price: str
    initial_stop_price: str
    initial_take_price: str
    locked_exit_profile: str

    def __post_init__(self) -> None:
        if type(self.side) is not str or self.side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        if type(self.source_plan_bar_open_time_ms) is not int:
            raise TypeError("source_plan_bar_open_time_ms must be a JSON integer")
        _require_exact_decimal_text(self.planned_entry_price, "planned_entry_price")
        _require_exact_decimal_text(self.initial_stop_price, "initial_stop_price")
        _require_positive_exact_decimal_text(self.initial_take_price, "initial_take_price")
        if type(self.locked_exit_profile) is not str:
            raise TypeError("locked_exit_profile must be a string")


@dataclass(frozen=True, slots=True)
class EntryPackageRequest:
    """One Runtime-owned desired entry package or its explicit absence."""

    strategy_instance_id: str
    trade_cycle_id: str
    ticker: str
    desired_entry: EntryPackageWireDesiredEntry | None
    risk_multiplier: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_non_empty_string(self.ticker, "ticker")
        if (
            self.desired_entry is not None
            and type(self.desired_entry) is not EntryPackageWireDesiredEntry
        ):
            raise TypeError("desired_entry must be EntryPackageWireDesiredEntry or None")
        _require_positive_exact_decimal_text(self.risk_multiplier, "risk_multiplier")


@dataclass(frozen=True, slots=True)
class EntryPackageApplied:
    """ABI acknowledgement that the complete attached package is applied."""

    strategy_instance_id: str
    trade_cycle_id: str
    applied_desired_entry: EntryPackageWireDesiredEntry
    accepted_risk_multiplier: str
    calculated_quantity: str

    status: ClassVar[Literal["entry_package_applied"]] = "entry_package_applied"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        if type(self.applied_desired_entry) is not EntryPackageWireDesiredEntry:
            raise TypeError("applied_desired_entry must be EntryPackageWireDesiredEntry")
        _require_positive_exact_decimal_text(
            self.accepted_risk_multiplier, "accepted_risk_multiplier"
        )
        _require_exact_decimal_text(self.calculated_quantity, "calculated_quantity")


@dataclass(frozen=True, slots=True)
class EntryPackageAbsent:
    """ABI acknowledgement that the desired package is absent."""

    strategy_instance_id: str
    trade_cycle_id: str

    status: ClassVar[Literal["entry_package_absent"]] = "entry_package_absent"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")


@dataclass(frozen=True, slots=True)
class EntryPackageValidationDetail:
    """One ABI-provided validation detail."""

    path: str
    message: str

    def __post_init__(self) -> None:
        if type(self.path) is not str:
            raise TypeError("validation detail path must be a string")
        if type(self.message) is not str:
            raise TypeError("validation detail message must be a string")


@dataclass(frozen=True, slots=True)
class EntryPackageMalformedJson:
    """Typed HTTP 400 public ABI result."""

    message: str

    code: ClassVar[Literal["malformed_json"]] = "malformed_json"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.message, "message")


@dataclass(frozen=True, slots=True)
class EntryPackageUnsupportedMediaType:
    """Typed HTTP 415 public ABI result."""

    message: str

    code: ClassVar[Literal["unsupported_media_type"]] = "unsupported_media_type"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.message, "message")


@dataclass(frozen=True, slots=True)
class EntryPackageValidationFailed:
    """Typed HTTP 422 public ABI result with preserved details."""

    message: str
    details: tuple[EntryPackageValidationDetail, ...]

    code: ClassVar[Literal["validation_failed"]] = "validation_failed"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.message, "message")
        if type(self.details) is not tuple or len(self.details) == 0:
            raise ValueError("validation details must be a non-empty tuple")
        if any(type(detail) is not EntryPackageValidationDetail for detail in self.details):
            raise TypeError("validation details must contain EntryPackageValidationDetail")


@dataclass(frozen=True, slots=True)
class EntryPackageInternalError:
    """Typed HTTP 500 public ABI result."""

    message: str

    code: ClassVar[Literal["internal_error"]] = "internal_error"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.message, "message")


EntryPackagePublicError = (
    EntryPackageMalformedJson
    | EntryPackageUnsupportedMediaType
    | EntryPackageValidationFailed
    | EntryPackageInternalError
)
EntryPackageResult = EntryPackageApplied | EntryPackageAbsent | EntryPackagePublicError


def _require_non_empty_string(value: str, name: str) -> None:
    if type(value) is not str or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty string")


def _require_exact_decimal_text(value: str, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact-decimal string")
    if not is_exact_decimal_text(value):
        raise ValueError(f"{name} must be exact-decimal text")


def _require_positive_exact_decimal_text(value: str, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a positive exact-decimal string")
    if not is_positive_exact_decimal_text(value):
        raise ValueError(f"{name} must be positive exact-decimal text")


def _analyze_exact_decimal_text(value: str) -> tuple[bool, bool]:
    if type(value) is not str or len(value) == 0:
        return False, False

    index = 0
    negative = False
    if value[index] in {"+", "-"}:
        negative = value[index] == "-"
        index += 1

    digit_count = 0
    coefficient_has_non_zero_digit = False
    while index < len(value) and _is_digit(value[index]):
        coefficient_has_non_zero_digit = (
            coefficient_has_non_zero_digit or value[index] != "0"
        )
        digit_count += 1
        index += 1

    if index < len(value) and value[index] == ".":
        index += 1
        while index < len(value) and _is_digit(value[index]):
            coefficient_has_non_zero_digit = (
                coefficient_has_non_zero_digit or value[index] != "0"
            )
            digit_count += 1
            index += 1

    if digit_count == 0:
        return False, False

    if index < len(value) and value[index] in {"e", "E"}:
        index += 1
        if index < len(value) and value[index] in {"+", "-"}:
            index += 1
        exponent_start = index
        while index < len(value) and _is_digit(value[index]):
            index += 1
        if index == exponent_start:
            return False, False

    if index != len(value):
        return False, False

    return True, not negative and coefficient_has_non_zero_digit


def _is_digit(value: str) -> bool:
    return "0" <= value <= "9"
