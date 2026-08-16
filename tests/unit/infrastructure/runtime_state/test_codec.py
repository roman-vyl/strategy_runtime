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
    PendingEntryRecovery,
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


# ---------------------------------------------------------------------------
# A record is a complete snapshot: a nullable field must still be present
# with an explicit JSON `null`. Omitting the key entirely is a schema
# violation, not an implicit null -- `.get(...)` must never paper over it.
# ---------------------------------------------------------------------------


def test_decode_rejects_missing_current_trade_cycle_key() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    assert envelope["current_trade_cycle"] is None
    del envelope["current_trade_cycle"]

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_rejects_missing_frozen_entry_context_key() -> None:
    envelope = json.loads(encode_state_line(_complete_state()))
    del envelope["current_trade_cycle"]["frozen_entry_context"]

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_rejects_missing_latest_confirmed_management_protection_key() -> None:
    envelope = json.loads(encode_state_line(_complete_state()))
    del envelope["current_trade_cycle"]["latest_confirmed_management_protection"]

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_rejects_missing_take_price_key() -> None:
    envelope = json.loads(encode_state_line(_complete_state()))
    del envelope["current_trade_cycle"]["latest_confirmed_management_protection"]["take_price"]

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_decode_accepts_explicit_null_current_trade_cycle() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    envelope["current_trade_cycle"] = None

    decoded = decode_state_line(json.dumps(envelope))

    assert decoded.current_trade_cycle is None


def test_decode_accepts_explicit_null_frozen_entry_context_and_protection() -> None:
    bare_cycle_state = replace(
        _bare_state(),
        current_trade_cycle=CurrentTradeCycle(
            trade_cycle_id="cycle-1",
            applied_entry_package=AppliedEntryPackage(
                applied_desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
                calculated_quantity="0.0100",
            ),
        ),
    )

    decoded = decode_state_line(encode_state_line(bare_cycle_state))

    assert decoded.current_trade_cycle is not None
    assert decoded.current_trade_cycle.frozen_entry_context is None
    assert decoded.current_trade_cycle.latest_confirmed_management_protection is None


def test_decode_accepts_explicit_null_take_price() -> None:
    envelope = json.loads(encode_state_line(_complete_state()))
    envelope["current_trade_cycle"]["latest_confirmed_management_protection"]["take_price"] = None

    decoded = decode_state_line(json.dumps(envelope))

    assert decoded.current_trade_cycle is not None
    protection = decoded.current_trade_cycle.latest_confirmed_management_protection
    assert protection is not None
    assert protection.take_price is None


# ---------------------------------------------------------------------------
# schema_version 1 <-> 2: pending_entry_recovery (see task 8.6).
# ---------------------------------------------------------------------------


def test_every_new_write_encodes_schema_version_2_with_pending_entry_recovery_key() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))

    assert envelope["schema_version"] == 2
    assert envelope["pending_entry_recovery"] is None


def test_round_trip_with_pending_entry_recovery_set() -> None:
    state = replace(_bare_state(), pending_entry_recovery=PendingEntryRecovery("cycle-1"))

    decoded = decode_state_line(encode_state_line(state))

    assert decoded == state
    assert decoded.pending_entry_recovery == PendingEntryRecovery("cycle-1")


def test_schema_version_1_line_decodes_with_no_pending_recovery_marker() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    del envelope["pending_entry_recovery"]
    envelope["schema_version"] = 1

    decoded = decode_state_line(json.dumps(envelope))

    assert decoded.pending_entry_recovery is None


def test_schema_version_1_line_rejects_an_unexpected_pending_entry_recovery_key() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    envelope["schema_version"] = 1

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_schema_version_2_line_requires_the_pending_entry_recovery_key() -> None:
    envelope = json.loads(encode_state_line(_bare_state()))
    del envelope["pending_entry_recovery"]

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))


def test_schema_version_2_line_decodes_a_present_pending_entry_recovery_marker() -> None:
    state = replace(_bare_state(), pending_entry_recovery=PendingEntryRecovery("cycle-7"))
    envelope = json.loads(encode_state_line(state))
    assert envelope["schema_version"] == 2

    decoded = decode_state_line(json.dumps(envelope))

    assert decoded.pending_entry_recovery == PendingEntryRecovery("cycle-7")


def test_decode_rejects_unknown_field_in_pending_entry_recovery() -> None:
    state = replace(_bare_state(), pending_entry_recovery=PendingEntryRecovery("cycle-1"))
    envelope = json.loads(encode_state_line(state))
    envelope["pending_entry_recovery"]["unexpected_field"] = "surprise"

    with pytest.raises(StateRecordDecodeError):
        decode_state_line(json.dumps(envelope))
