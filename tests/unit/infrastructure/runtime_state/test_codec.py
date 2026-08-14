import json
from dataclasses import replace

import pytest

from strategy_runtime.infrastructure.runtime_state.codec import (
    StateRecordDecodeError,
    decode_state_line,
    encode_state_line,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)


def _bare_state() -> StrategyInstanceRuntimeState:
    return InMemoryStrategyInstanceRuntimeStateRepository().get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id="ema_pullback:abc",
            strategy_id="ema_pullback",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={"ema": {"periods": [20, 200]}},
            source_path="ema-pullback.json",
        )
    )


def _complete_state() -> StrategyInstanceRuntimeState:
    cycle = CurrentTradeCycle(
        trade_cycle_id="cycle-1",
        applied_entry_package=AppliedEntryPackage(
            applied_desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
            calculated_quantity="0.0100",
        ),
        frozen_entry_context=FrozenExecutedEntryContext(
            desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
            first_fill_at_ms=901,
            entry_bar_open_time_ms=900,
        ),
        latest_confirmed_management_protection=DesiredProtection(
            stop_price="99.5", take_price="104"
        ),
    )
    return replace(_bare_state(), risk_multiplier="2.500", current_trade_cycle=cycle)


def test_round_trip_with_no_current_trade_cycle() -> None:
    state = _bare_state()

    decoded = decode_state_line(encode_state_line(state))

    assert decoded == state


def test_round_trip_with_complete_current_trade_cycle() -> None:
    state = _complete_state()

    decoded = decode_state_line(encode_state_line(state))

    assert decoded == state


def test_encoded_line_is_one_compact_json_line() -> None:
    line = encode_state_line(_complete_state())

    assert "\n" not in line
    json.loads(line)  # does not raise


def test_encode_rejects_wrong_type() -> None:
    with pytest.raises(TypeError):
        encode_state_line("not a state")  # type: ignore[arg-type]


def test_decode_raises_json_decode_error_for_unparsable_syntax() -> None:
    with pytest.raises(json.JSONDecodeError):
        decode_state_line("{not valid json")


def test_decode_raises_state_record_decode_error_for_missing_field() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    del envelope["risk_multiplier"]

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_raises_state_record_decode_error_for_invalid_domain_value() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    envelope["risk_multiplier"] = "not-a-decimal"

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_raises_state_record_decode_error_for_unsupported_schema_version() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    envelope["schema_version"] = 999

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_raises_state_record_decode_error_for_non_object_envelope() -> None:
    with pytest.raises(StateRecordDecodeError):
        decode_state_line("42")


def test_decode_rejects_unknown_top_level_envelope_field() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    envelope["unexpected_field"] = "surprise"

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_rejects_unknown_field_in_current_trade_cycle() -> None:
    envelope = json.loads(encode_state_line(_complete_state()))
    envelope["current_trade_cycle"]["unexpected_field"] = "surprise"

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_rejects_unknown_field_in_desired_entry() -> None:
    envelope = json.loads(encode_state_line(_complete_state()))
    envelope["current_trade_cycle"]["applied_entry_package"]["applied_desired_entry"][
        "unexpected_field"
    ] = "surprise"

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_rejects_unknown_field_in_registered_spec_snapshot() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    envelope["registered_spec_snapshot"]["unexpected_field"] = "surprise"

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_does_not_restrict_keys_inside_raw_spec() -> None:
    bare = _bare_state()
    state = replace(
        bare,
        registered_spec_snapshot=replace(
            bare.registered_spec_snapshot,
            raw_spec={"anything_goes": {"nested": [1, 2, 3]}, "another_field": True},
        ),
    )

    decoded = decode_state_line(encode_state_line(state))

    assert decoded.registered_spec_snapshot.raw_spec["anything_goes"]["nested"] == (1, 2, 3)
    assert decoded.registered_spec_snapshot.raw_spec["another_field"] is True
