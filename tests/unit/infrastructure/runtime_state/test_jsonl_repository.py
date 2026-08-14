import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from strategy_runtime.infrastructure.runtime_state import (
    JsonlStrategyInstanceRuntimeStateRepository,
    StrategyInstanceStateReplayError,
    StrategyInstanceStateStorePoisoned,
)
from strategy_runtime.infrastructure.runtime_state.codec import encode_state_line
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.errors import (
    StrategyInstanceIdentityConflict,
    StrategyInstanceRegistrationConflict,
    StrategyInstanceStateNotFound,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
)


def make_request(
    *,
    strategy_instance_id: str = "ema_pullback:abc",
    strategy_id: str = "ema_pullback",
    instrument: str = "BTCUSDT.P",
    base_timeframe: str = "5m",
    raw_spec=None,
    source_path: str = "ema-pullback.json",
) -> GetOrCreateStrategyInstanceRuntimeStateRequest:
    return GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=strategy_instance_id,
        strategy_id=strategy_id,
        instrument=instrument,
        base_timeframe=base_timeframe,
        raw_spec=raw_spec or {"ema": 200},
        source_path=source_path,
    )


def _complete_cycle(trade_cycle_id: str, *, quantity: str) -> CurrentTradeCycle:
    return CurrentTradeCycle(
        trade_cycle_id=trade_cycle_id,
        applied_entry_package=AppliedEntryPackage(
            applied_desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
            calculated_quantity=quantity,
        ),
    )


# ---------------------------------------------------------------------------
# Same get_or_create/get/save semantics as the in-memory repository.
# ---------------------------------------------------------------------------


def test_missing_state_is_created_with_no_cycle(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")

    state = repository.get_or_create(make_request())

    assert state.risk_multiplier == "1"
    assert state.current_trade_cycle is None


def test_existing_instance_is_returned_unchanged(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    first = repository.get_or_create(make_request())

    second = repository.get_or_create(make_request(instrument="ETHUSDT.P", raw_spec={"ema": 300}))

    assert second is first
    assert second.registered_spec_snapshot.instrument == "BTCUSDT.P"


def test_existing_instance_rejects_conflicting_strategy_id(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    repository.get_or_create(make_request())

    with pytest.raises(StrategyInstanceIdentityConflict):
        repository.get_or_create(make_request(strategy_id="different"))


def test_get_returns_none_for_unknown_identity(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    assert repository.get("missing") is None


def test_save_replaces_the_complete_registered_aggregate(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    initial = repository.get_or_create(make_request())
    cycle = _complete_cycle("cycle-1", quantity="0.01")
    replacement = replace(initial, risk_multiplier="2.500", current_trade_cycle=cycle)

    saved = repository.save(replacement)

    assert saved is replacement
    assert repository.get(initial.strategy_instance_id) is replacement


def test_save_rejects_unregistered_identity(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    other_repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "other.jsonl")
    state = other_repository.get_or_create(make_request(strategy_instance_id="unregistered"))

    with pytest.raises(StrategyInstanceStateNotFound):
        repository.save(state)


def test_save_rejects_strategy_identity_change(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    initial = repository.get_or_create(make_request())

    with pytest.raises(StrategyInstanceIdentityConflict):
        repository.save(replace(initial, strategy_id="other"))


def test_save_rejects_registered_snapshot_change(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "state.jsonl")
    initial = repository.get_or_create(make_request())
    changed_snapshot = RegisteredSpecSnapshot(
        instrument="ETHUSDT.P",
        base_timeframe="1h",
        raw_spec={"ema": 300},
        source_path="other.json",
    )

    with pytest.raises(StrategyInstanceRegistrationConflict):
        repository.save(replace(initial, registered_spec_snapshot=changed_snapshot))


# ---------------------------------------------------------------------------
# Durability: a fresh repository constructed against the same file recovers
# the latest saved state.
# ---------------------------------------------------------------------------


def test_state_survives_a_fresh_repository_instance_against_the_same_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.jsonl"
    first_repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    initial = first_repository.get_or_create(make_request())
    saved = first_repository.save(
        replace(
            initial,
            risk_multiplier="3",
            current_trade_cycle=_complete_cycle("c1", quantity="0.02"),
        )
    )

    second_repository = JsonlStrategyInstanceRuntimeStateRepository(path)

    recovered = second_repository.get(initial.strategy_instance_id)
    assert recovered == saved
    assert recovered is not saved  # replayed from disk, not the same object


def test_multiple_keys_and_superseding_records_survive_replay(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    a = repository.get_or_create(make_request(strategy_instance_id="a"))
    b = repository.get_or_create(make_request(strategy_instance_id="b"))
    repository.save(replace(a, risk_multiplier="2"))
    repository.save(replace(a, risk_multiplier="4"))
    repository.save(replace(b, risk_multiplier="5"))

    replayed = JsonlStrategyInstanceRuntimeStateRepository(path)

    assert replayed.get("a").risk_multiplier == "4"
    assert replayed.get("b").risk_multiplier == "5"


def test_absent_file_replays_to_empty_index(tmp_path: Path) -> None:
    repository = JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "does-not-exist.jsonl")
    assert repository.get("anything") is None


def test_empty_file_replays_to_empty_index(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    path.write_text("", encoding="utf-8")
    repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    assert repository.get("anything") is None


# ---------------------------------------------------------------------------
# Fail-closed replay contract: only a JSON-parse failure confined to the
# file's last line is tolerated. Everything else fails closed.
# ---------------------------------------------------------------------------


def test_json_parse_failure_on_non_last_line_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    good_line = encode_state_line(
        JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "scratch.jsonl").get_or_create(
            make_request()
        )
    )
    path.write_text(f"{{not valid json\n{good_line}\n", encoding="utf-8")

    with pytest.raises(StrategyInstanceStateReplayError):
        JsonlStrategyInstanceRuntimeStateRepository(path)


def test_json_parse_failure_only_on_last_line_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    good_line = encode_state_line(
        JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "scratch.jsonl").get_or_create(
            make_request()
        )
    )
    path.write_text(f"{good_line}\n{{truncated by a crash mid-appen", encoding="utf-8")

    repository = JsonlStrategyInstanceRuntimeStateRepository(path)

    assert repository.get("ema_pullback:abc") is not None


def test_file_whose_only_line_is_a_json_parse_failure_replays_to_empty_index(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.jsonl"
    path.write_text("{truncated", encoding="utf-8")

    repository = JsonlStrategyInstanceRuntimeStateRepository(path)

    assert repository.get("anything") is None


def test_last_line_that_is_valid_json_but_fails_schema_validation_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.jsonl"
    envelope = json.loads(
        encode_state_line(
            JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "scratch.jsonl").get_or_create(
                make_request()
            )
        )
    )
    envelope["risk_multiplier"] = "not-a-decimal"
    path.write_text(f"{json.dumps(envelope)}\n", encoding="utf-8")

    with pytest.raises(StrategyInstanceStateReplayError):
        JsonlStrategyInstanceRuntimeStateRepository(path)


def test_non_last_line_that_is_valid_json_but_fails_schema_validation_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.jsonl"
    good_line = encode_state_line(
        JsonlStrategyInstanceRuntimeStateRepository(tmp_path / "scratch.jsonl").get_or_create(
            make_request()
        )
    )
    envelope = json.loads(good_line)
    envelope["risk_multiplier"] = "not-a-decimal"
    invalid_line = json.dumps(envelope)
    path.write_text(f"{invalid_line}\n{good_line}\n", encoding="utf-8")

    with pytest.raises(StrategyInstanceStateReplayError):
        JsonlStrategyInstanceRuntimeStateRepository(path)


# ---------------------------------------------------------------------------
# Physical append ordering and failure semantics.
# ---------------------------------------------------------------------------


def test_concurrent_saves_for_different_instances_never_interleave_mid_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.jsonl"
    repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    instance_ids = [f"instance-{i}" for i in range(8)]
    for instance_id in instance_ids:
        repository.get_or_create(make_request(strategy_instance_id=instance_id))
    start = Barrier(len(instance_ids))

    def save_many(instance_id: str) -> None:
        start.wait()
        state = repository.get(instance_id)
        for i in range(20):
            state = repository.save(replace(state, risk_multiplier=str(i + 1)))

    with ThreadPoolExecutor(max_workers=len(instance_ids)) as executor:
        futures = [executor.submit(save_many, instance_id) for instance_id in instance_ids]
        for future in futures:
            future.result()

    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        json.loads(line)  # every physical line is one complete, parseable record
    replayed = JsonlStrategyInstanceRuntimeStateRepository(path)
    for instance_id in instance_ids:
        assert replayed.get(instance_id).risk_multiplier == "20"


def test_encode_failure_before_physical_write_does_not_poison_or_update_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in serialization -- before any file write is attempted --
    is not an ambiguous physical outcome, so it must not poison the
    repository: the caller sees the exception, the in-memory index is
    unchanged, and the repository keeps serving normally afterward."""
    path = tmp_path / "state.jsonl"
    repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    initial = repository.get_or_create(make_request())

    def _boom(_state: object) -> str:
        raise ValueError("simulated serialization failure")

    monkeypatch.setattr(
        "strategy_runtime.infrastructure.runtime_state.jsonl_repository.encode_state_line", _boom
    )

    with pytest.raises(ValueError):
        repository.save(replace(initial, risk_multiplier="9"))

    monkeypatch.undo()
    assert repository.get(initial.strategy_instance_id) is initial
    again = repository.save(replace(initial, risk_multiplier="9"))
    assert repository.get(initial.strategy_instance_id) is again


def test_physical_write_failure_poisons_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure from the physical write onward (here: `os.fsync`) leaves
    an ambiguous on-disk outcome -- the preceding `write`/`flush` may have
    already reached the file. The repository must not keep serving from
    that point: it poisons itself, and every later call fails closed."""
    path = tmp_path / "state.jsonl"
    repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    initial = repository.get_or_create(make_request())

    def _boom(_fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", _boom)

    with pytest.raises(OSError):
        repository.save(replace(initial, risk_multiplier="9"))

    with pytest.raises(StrategyInstanceStateStorePoisoned):
        repository.get(initial.strategy_instance_id)
    with pytest.raises(StrategyInstanceStateStorePoisoned):
        repository.get_or_create(make_request(strategy_instance_id="another-instance"))
    with pytest.raises(StrategyInstanceStateStorePoisoned):
        repository.save(initial)


def test_physical_write_failure_during_creation_poisons_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.jsonl"
    repository = JsonlStrategyInstanceRuntimeStateRepository(path)

    def _boom(_fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", _boom)

    with pytest.raises(OSError):
        repository.get_or_create(make_request())

    with pytest.raises(StrategyInstanceStateStorePoisoned):
        repository.get("anything")
