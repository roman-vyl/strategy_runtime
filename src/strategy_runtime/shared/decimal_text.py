"""Exact decimal-text helpers shared across transport boundaries."""

from decimal import Decimal, InvalidOperation


def is_exact_decimal_text(value: object) -> bool:
    """Return whether value uses the Runtime finite exact-decimal grammar."""
    valid, _ = _analyze_exact_decimal_text(value)
    return valid


def is_positive_exact_decimal_text(value: object) -> bool:
    """Return whether exact-decimal text represents a value greater than zero."""
    valid, positive = _analyze_exact_decimal_text(value)
    return valid and positive


def normalize_decimal_text(value: str) -> str:
    """Validate and return canonical non-exponent decimal text without float conversion."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("decimal text must be a non-empty string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal text") from exc
    if not number.is_finite():
        raise ValueError("decimal text must be finite")
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in {"-0", ""}:
        normalized = "0"
    return normalized


def _analyze_exact_decimal_text(value: object) -> tuple[bool, bool]:
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
        coefficient_has_non_zero_digit = coefficient_has_non_zero_digit or value[index] != "0"
        digit_count += 1
        index += 1

    if index < len(value) and value[index] == ".":
        index += 1
        while index < len(value) and _is_digit(value[index]):
            coefficient_has_non_zero_digit = coefficient_has_non_zero_digit or value[index] != "0"
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
