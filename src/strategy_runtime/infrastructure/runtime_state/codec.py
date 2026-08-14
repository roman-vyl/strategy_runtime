"""JSON codec for durable on-disk `StrategyInstanceRuntimeState` records.

Encoding produces one compact JSON line per snapshot. Decoding reconstructs
the aggregate through its existing frozen-dataclass constructors, so the
domain models' own `__post_init__` validation runs on every replayed
record -- there is no separate recovery-side schema to keep in sync.

Every persisted structure -- the envelope, `CurrentTradeCycle`,
`AppliedEntryPackage`, `DesiredEntry`, `FrozenExecutedEntryContext`, and
`DesiredProtection` -- is decoded against an exact set of allowed keys, so
an unrecognized field fails loudly instead of being silently dropped. The
one deliberate exception is `raw_spec`, which remains an opaque,
free-form JSON object -- its own keys are never restricted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.recipes.position_management import DesiredProtection
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    FrozenExecutedEntryContext,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)

_SCHEMA_VERSION: Final = 1

_ENVELOPE_KEYS: Final = frozenset(
    {
        "schema_version",
        "strategy_instance_id",
        "strategy_id",
        "registered_spec_snapshot",
        "risk_multiplier",
        "current_trade_cycle",
    }
)
_SNAPSHOT_KEYS: Final = frozenset({"instrument", "base_timeframe", "raw_spec", "source_path"})
_CYCLE_KEYS: Final = frozenset(
    {
        "trade_cycle_id",
        "applied_entry_package",
        "frozen_entry_context",
        "latest_confirmed_management_protection",
    }
)
_APPLIED_ENTRY_PACKAGE_KEYS: Final = frozenset({"applied_desired_entry", "calculated_quantity"})
_DESIRED_ENTRY_KEYS: Final = frozenset(
    {
        "side",
        "source_plan_bar_open_time_ms",
        "planned_entry_price",
        "initial_stop_price",
        "initial_take_price",
        "locked_exit_profile",
    }
)
_FROZEN_ENTRY_CONTEXT_KEYS: Final = frozenset(
    {"desired_entry", "first_fill_at_ms", "entry_bar_open_time_ms"}
)
_DESIRED_PROTECTION_KEYS: Final = frozenset({"stop_price", "take_price"})


class StateRecordDecodeError(ValueError):
    """A line parsed as syntactically valid JSON but failed envelope,
    schema, or domain validation -- distinct from `json.JSONDecodeError`
    so callers can implement the truncated-tail-vs-corruption replay
    contract (only a JSON parse failure on the file's last line is
    tolerated; this error is never tolerated, regardless of position)."""


def encode_state_line(state: StrategyInstanceRuntimeState) -> str:
    """Serialize one complete snapshot to one compact, deterministic JSON line."""
    if type(state) is not StrategyInstanceRuntimeState:
        raise TypeError("state must be StrategyInstanceRuntimeState")
    envelope: dict[str, Any] = {"schema_version": _SCHEMA_VERSION, **_encode_aggregate(state)}
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def decode_state_line(line: str) -> StrategyInstanceRuntimeState:
    """Parse one durable JSONL line back into a complete `StrategyInstanceRuntimeState`.

    Raises `json.JSONDecodeError` for a syntactically invalid line, and
    `StateRecordDecodeError` for a syntactically valid line whose envelope,
    schema, or domain content is invalid.
    """
    envelope = json.loads(line)
    try:
        return _decode_envelope(envelope)
    except (TypeError, ValueError, KeyError) as exc:
        raise StateRecordDecodeError(str(exc)) from exc


def _encode_aggregate(state: StrategyInstanceRuntimeState) -> dict[str, Any]:
    return {
        "strategy_instance_id": state.strategy_instance_id,
        "strategy_id": state.strategy_id,
        "registered_spec_snapshot": _encode_snapshot(state.registered_spec_snapshot),
        "risk_multiplier": state.risk_multiplier,
        "current_trade_cycle": (
            _encode_cycle(state.current_trade_cycle)
            if state.current_trade_cycle is not None
            else None
        ),
    }


def _encode_snapshot(snapshot: RegisteredSpecSnapshot) -> dict[str, Any]:
    return {
        "instrument": snapshot.instrument,
        "base_timeframe": snapshot.base_timeframe,
        "raw_spec": _to_plain_json(snapshot.raw_spec),
        "source_path": snapshot.source_path,
    }


def _encode_cycle(cycle: CurrentTradeCycle) -> dict[str, Any]:
    return {
        "trade_cycle_id": cycle.trade_cycle_id,
        "applied_entry_package": _encode_applied_entry_package(cycle.applied_entry_package),
        "frozen_entry_context": (
            _encode_frozen_entry_context(cycle.frozen_entry_context)
            if cycle.frozen_entry_context is not None
            else None
        ),
        "latest_confirmed_management_protection": (
            _encode_desired_protection(cycle.latest_confirmed_management_protection)
            if cycle.latest_confirmed_management_protection is not None
            else None
        ),
    }


def _encode_applied_entry_package(package: AppliedEntryPackage) -> dict[str, Any]:
    return {
        "applied_desired_entry": _encode_desired_entry(package.applied_desired_entry),
        "calculated_quantity": package.calculated_quantity,
    }


def _encode_desired_entry(entry: DesiredEntry) -> dict[str, Any]:
    return {
        "side": entry.side,
        "source_plan_bar_open_time_ms": entry.source_plan_bar_open_time_ms,
        "planned_entry_price": entry.planned_entry_price,
        "initial_stop_price": entry.initial_stop_price,
        "initial_take_price": entry.initial_take_price,
        "locked_exit_profile": entry.locked_exit_profile,
    }


def _encode_frozen_entry_context(context: FrozenExecutedEntryContext) -> dict[str, Any]:
    return {
        "desired_entry": _encode_desired_entry(context.desired_entry),
        "first_fill_at_ms": context.first_fill_at_ms,
        "entry_bar_open_time_ms": context.entry_bar_open_time_ms,
    }


def _encode_desired_protection(protection: DesiredProtection) -> dict[str, Any]:
    return {"stop_price": protection.stop_price, "take_price": protection.take_price}


def _to_plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_plain_json(item) for item in value]
    return value


def _reject_unknown_keys(data: dict[str, Any], allowed: frozenset[str], *, where: str) -> None:
    unknown = data.keys() - allowed
    if unknown:
        raise ValueError(f"{where} has unknown field(s): {sorted(unknown)}")


def _decode_envelope(envelope: Any) -> StrategyInstanceRuntimeState:
    if not isinstance(envelope, dict):
        raise TypeError("record must be a JSON object")
    _reject_unknown_keys(envelope, _ENVELOPE_KEYS, where="envelope")
    if envelope.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported or missing schema_version")
    return _decode_aggregate(envelope)


def _decode_aggregate(data: dict[str, Any]) -> StrategyInstanceRuntimeState:
    current_trade_cycle_data = data.get("current_trade_cycle")
    return StrategyInstanceRuntimeState(
        strategy_instance_id=data["strategy_instance_id"],
        strategy_id=data["strategy_id"],
        registered_spec_snapshot=_decode_snapshot(data["registered_spec_snapshot"]),
        risk_multiplier=data["risk_multiplier"],
        current_trade_cycle=(
            _decode_cycle(current_trade_cycle_data)
            if current_trade_cycle_data is not None
            else None
        ),
    )


def _decode_snapshot(data: Any) -> RegisteredSpecSnapshot:
    if not isinstance(data, dict):
        raise TypeError("registered_spec_snapshot must be a JSON object")
    _reject_unknown_keys(data, _SNAPSHOT_KEYS, where="registered_spec_snapshot")
    return RegisteredSpecSnapshot(
        instrument=data["instrument"],
        base_timeframe=data["base_timeframe"],
        raw_spec=data["raw_spec"],
        source_path=data["source_path"],
    )


def _decode_cycle(data: Any) -> CurrentTradeCycle:
    if not isinstance(data, dict):
        raise TypeError("current_trade_cycle must be a JSON object")
    _reject_unknown_keys(data, _CYCLE_KEYS, where="current_trade_cycle")
    frozen_entry_context_data = data.get("frozen_entry_context")
    protection_data = data.get("latest_confirmed_management_protection")
    return CurrentTradeCycle(
        trade_cycle_id=data["trade_cycle_id"],
        applied_entry_package=_decode_applied_entry_package(data["applied_entry_package"]),
        frozen_entry_context=(
            _decode_frozen_entry_context(frozen_entry_context_data)
            if frozen_entry_context_data is not None
            else None
        ),
        latest_confirmed_management_protection=(
            _decode_desired_protection(protection_data) if protection_data is not None else None
        ),
    )


def _decode_applied_entry_package(data: Any) -> AppliedEntryPackage:
    if not isinstance(data, dict):
        raise TypeError("applied_entry_package must be a JSON object")
    _reject_unknown_keys(data, _APPLIED_ENTRY_PACKAGE_KEYS, where="applied_entry_package")
    return AppliedEntryPackage(
        applied_desired_entry=_decode_desired_entry(data["applied_desired_entry"]),
        calculated_quantity=data["calculated_quantity"],
    )


def _decode_desired_entry(data: Any) -> DesiredEntry:
    if not isinstance(data, dict):
        raise TypeError("desired_entry must be a JSON object")
    _reject_unknown_keys(data, _DESIRED_ENTRY_KEYS, where="desired_entry")
    return DesiredEntry(
        side=data["side"],
        source_plan_bar_open_time_ms=data["source_plan_bar_open_time_ms"],
        planned_entry_price=data["planned_entry_price"],
        initial_stop_price=data["initial_stop_price"],
        initial_take_price=data["initial_take_price"],
        locked_exit_profile=data["locked_exit_profile"],
    )


def _decode_frozen_entry_context(data: Any) -> FrozenExecutedEntryContext:
    if not isinstance(data, dict):
        raise TypeError("frozen_entry_context must be a JSON object")
    _reject_unknown_keys(data, _FROZEN_ENTRY_CONTEXT_KEYS, where="frozen_entry_context")
    return FrozenExecutedEntryContext(
        desired_entry=_decode_desired_entry(data["desired_entry"]),
        first_fill_at_ms=data["first_fill_at_ms"],
        entry_bar_open_time_ms=data["entry_bar_open_time_ms"],
    )


def _decode_desired_protection(data: Any) -> DesiredProtection:
    if not isinstance(data, dict):
        raise TypeError("latest_confirmed_management_protection must be a JSON object")
    _reject_unknown_keys(
        data, _DESIRED_PROTECTION_KEYS, where="latest_confirmed_management_protection"
    )
    return DesiredProtection(
        stop_price=data["stop_price"],
        take_price=data.get("take_price"),
    )
