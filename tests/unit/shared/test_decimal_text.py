import pytest

from strategy_runtime.shared.decimal_text import (
    is_exact_decimal_text,
    is_positive_exact_decimal_text,
)


@pytest.mark.parametrize(
    "value",
    ["0", "-0", "+0", ".5", "1.", "-12.3400", "1e3", "+1.25E-2"],
)
def test_exact_decimal_predicate_accepts_abi_grammar(value: str) -> None:
    assert is_exact_decimal_text(value)


@pytest.mark.parametrize(
    "value",
    [None, 1, "", " 1", "1 ", "NaN", "Infinity", ".", "+", "1e", "1_000"],
)
def test_exact_decimal_predicate_rejects_non_contract_values(value: object) -> None:
    assert not is_exact_decimal_text(value)


@pytest.mark.parametrize("value", [".1", "+1", "1.00", "1e-3"])
def test_positive_exact_decimal_predicate_accepts_positive_values(value: str) -> None:
    assert is_positive_exact_decimal_text(value)


@pytest.mark.parametrize(
    "value",
    [None, 1, "", "0", "-0", "+0.0", "-1", "NaN", " 1", "1 "],
)
def test_positive_exact_decimal_predicate_rejects_other_values(
    value: object,
) -> None:
    assert not is_positive_exact_decimal_text(value)
