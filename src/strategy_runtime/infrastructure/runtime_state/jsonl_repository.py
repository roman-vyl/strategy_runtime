"""Durable, fsync-backed `StrategyInstanceRuntimeStateRepository`.

Every strategy instance shares one append-only JSONL file. A successful
`save(...)` (or the creation path of `get_or_create(...)`) has already been
serialized, appended, flushed, and `fsync`'d before it returns. At
construction, the repository replays that file once to recover the latest
valid snapshot per `strategy_instance_id`, before serving any call.

If the physical append itself (open/write/flush/`fsync`) fails partway,
the on-disk outcome is ambiguous -- bytes may or may not have reached the
file. Rather than continue serving from a store whose durability guarantee
that failure just broke, the repository poisons itself: every subsequent
call fails closed with `StrategyInstanceStateStorePoisoned` for the rest
of this instance's life. A failure before the physical write is attempted
(e.g. serialization) does not poison -- nothing ambiguous happened on disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

from strategy_runtime.infrastructure.runtime_state.codec import (
    StateRecordDecodeError,
    decode_state_line,
    encode_state_line,
)
from strategy_runtime.infrastructure.runtime_state.errors import (
    StrategyInstanceStateReplayError,
    StrategyInstanceStateStorePoisoned,
)
from strategy_runtime.runtime.state.errors import (
    StrategyInstanceIdentityConflict,
    StrategyInstanceRegistrationConflict,
    StrategyInstanceStateNotFound,
)
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)

_CANONICAL_INITIAL_RISK_MULTIPLIER = "1"


class JsonlStrategyInstanceRuntimeStateRepository:
    """File-backed repository: durable physical appends, in-memory reads."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        self._states: dict[str, StrategyInstanceRuntimeState] = _replay(path)
        self._poison: BaseException | None = None

    @property
    def path(self) -> Path:
        return self._path

    def get_or_create(
        self, request: GetOrCreateStrategyInstanceRuntimeStateRequest
    ) -> StrategyInstanceRuntimeState:
        with self._lock:
            self._check_not_poisoned()
            existing = self._states.get(request.strategy_instance_id)
            if existing is not None:
                if existing.strategy_id != request.strategy_id:
                    raise StrategyInstanceIdentityConflict(request.strategy_instance_id)
                return existing
            state = StrategyInstanceRuntimeState(
                strategy_instance_id=request.strategy_instance_id,
                strategy_id=request.strategy_id,
                registered_spec_snapshot=RegisteredSpecSnapshot(
                    instrument=request.instrument,
                    base_timeframe=request.base_timeframe,
                    raw_spec=request.raw_spec,
                    source_path=request.source_path,
                ),
                risk_multiplier=_CANONICAL_INITIAL_RISK_MULTIPLIER,
            )
            self._append(state)
            self._states[request.strategy_instance_id] = state
            return state

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        _require_strategy_instance_id(strategy_instance_id)
        with self._lock:
            self._check_not_poisoned()
            return self._states.get(strategy_instance_id)

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        if type(state) is not StrategyInstanceRuntimeState:
            raise TypeError("state must be StrategyInstanceRuntimeState")
        with self._lock:
            self._check_not_poisoned()
            existing = self._states.get(state.strategy_instance_id)
            if existing is None:
                raise StrategyInstanceStateNotFound(state.strategy_instance_id)
            if existing.strategy_id != state.strategy_id:
                raise StrategyInstanceIdentityConflict(state.strategy_instance_id)
            if existing.registered_spec_snapshot != state.registered_spec_snapshot:
                raise StrategyInstanceRegistrationConflict(state.strategy_instance_id)
            self._append(state)
            self._states[state.strategy_instance_id] = state
            return state

    def list_ids_with_pending_entry_recovery(self) -> tuple[str, ...]:
        with self._lock:
            self._check_not_poisoned()
            return tuple(
                strategy_instance_id
                for strategy_instance_id, state in self._states.items()
                if state.pending_entry_recovery is not None
            )

    def list_ids_with_pending_close_recovery(self) -> tuple[str, ...]:
        with self._lock:
            self._check_not_poisoned()
            return tuple(
                strategy_instance_id
                for strategy_instance_id, state in self._states.items()
                if state.pending_close_recovery is not None
            )

    def _check_not_poisoned(self) -> None:
        if self._poison is not None:
            raise StrategyInstanceStateStorePoisoned(
                f"{self._path}: a prior physical write failed with an ambiguous "
                "on-disk outcome; this repository instance no longer serves requests"
            ) from self._poison

    def _append(self, state: StrategyInstanceRuntimeState) -> None:
        """Serialize, append, flush, and `fsync` one line.

        Must complete before the caller updates its in-memory index --
        any exception here propagates without that update happening.
        Serialization failure does not poison the repository (no physical
        write was attempted); a failure from the physical write onward
        does, since its on-disk outcome is ambiguous.
        """
        line = encode_state_line(state)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException as exc:
            self._poison = exc
            raise


def _require_strategy_instance_id(strategy_instance_id: str) -> None:
    if type(strategy_instance_id) is not str or len(strategy_instance_id) == 0:
        raise ValueError("strategy_instance_id must be a non-empty string")


def _replay(path: Path) -> dict[str, StrategyInstanceRuntimeState]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    lines = text.splitlines()
    last_index = len(lines) - 1
    states: dict[str, StrategyInstanceRuntimeState] = {}
    for index, raw_line in enumerate(lines):
        try:
            state = decode_state_line(raw_line)
        except json.JSONDecodeError as exc:
            if index == last_index:
                # A JSON parse failure confined to the file's last line is a
                # truncated write left by a crash mid-append -- discard it
                # and keep whatever prior state each key already had.
                break
            raise StrategyInstanceStateReplayError(
                f"{path}: line {index + 1} is not the file's last line and cannot be parsed as JSON"
            ) from exc
        except StateRecordDecodeError as exc:
            raise StrategyInstanceStateReplayError(
                f"{path}: line {index + 1} parses as JSON but fails schema/domain validation"
            ) from exc
        else:
            states[state.strategy_instance_id] = state
    return states
