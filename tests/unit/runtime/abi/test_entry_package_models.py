from typing import cast

import pytest

from strategy_runtime.runtime.abi.entry_package_codec import encode_entry_package_request
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageRequest,
    EntryPackageWireDesiredEntry,
    is_exact_decimal_text,
    is_positive_exact_decimal_text,
)


def test_wire_desired_entry_preserves_abi_values_without_domain_normalization() -> None:
    desired_entry = EntryPackageWireDesiredEntry(
        side="short",
        source_plan_bar_open_time_ms=-1,
        planned_entry_price="-001.2300e+2",
        initial_stop_price="+999.00",
        initial_take_price="000.10e1",
        locked_exit_profile="",
    )

    assert desired_entry.source_plan_bar_open_time_ms == -1
    assert desired_entry.planned_entry_price == "-001.2300e+2"
    assert desired_entry.initial_stop_price == "+999.00"
    assert desired_entry.initial_take_price == "000.10e1"
    assert desired_entry.locked_exit_profile == ""


@pytest.mark.parametrize(
    "value",
    ["0", "-0", "+1", "001.2300", ".5", "1.", "1e+1000000", "-2E-3"],
)
def test_exact_decimal_grammar_accepts_abi_lexemes(value: str) -> None:
    assert is_exact_decimal_text(value)


@pytest.mark.parametrize("value", ["+1", "001.2300", ".5", "1.", "1e+1000000"])
def test_positive_exact_decimal_grammar_accepts_positive_abi_lexemes(value: str) -> None:
    assert is_positive_exact_decimal_text(value)


@pytest.mark.parametrize("value", ["", ".", "e1", "NaN", "Infinity", "1e", " 1", "1 "])
def test_exact_decimal_grammar_rejects_non_abi_lexemes(value: str) -> None:
    assert not is_exact_decimal_text(value)


@pytest.mark.parametrize("value", ["0", "-0", "-1", "-1e-3"])
def test_positive_exact_decimal_grammar_rejects_non_positive_values(value: str) -> None:
    assert not is_positive_exact_decimal_text(value)


def test_absence_request_keeps_mandatory_risk_and_closed_body() -> None:
    request = EntryPackageRequest(
        strategy_instance_id=" instance ",
        trade_cycle_id="cycle",
        ticker="BTCUSDT.P",
        desired_entry=None,
        risk_multiplier="+01.00",
    )

    assert encode_entry_package_request(request) == {
        "ticker": "BTCUSDT.P",
        "desired_entry": None,
        "risk_multiplier": "+01.00",
    }


@pytest.mark.parametrize("risk_multiplier", [None, "", "0", "-0", "-1", "NaN"])
def test_request_rejects_null_or_non_positive_risk(risk_multiplier: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        EntryPackageRequest(
            strategy_instance_id="instance",
            trade_cycle_id="cycle",
            ticker="BTCUSDT.P",
            desired_entry=None,
            risk_multiplier=cast("str", risk_multiplier),
        )


def test_request_requires_risk_multiplier_constructor_argument() -> None:
    with pytest.raises(TypeError):
        EntryPackageRequest(  # type: ignore[call-arg]
            strategy_instance_id="instance",
            trade_cycle_id="cycle",
            ticker="BTCUSDT.P",
            desired_entry=None,
        )


def test_wire_dto_rejects_boolean_timestamp() -> None:
    with pytest.raises(TypeError):
        EntryPackageWireDesiredEntry(
            side="long",
            source_plan_bar_open_time_ms=cast("int", True),
            planned_entry_price="1",
            initial_stop_price="1",
            initial_take_price="1",
            locked_exit_profile="",
        )
