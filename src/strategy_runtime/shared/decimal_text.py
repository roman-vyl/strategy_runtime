"""Exact decimal-text helpers shared across transport boundaries."""

from decimal import Decimal, InvalidOperation


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
