"""`StrategyDeleteService`: only a disabled strategy, the safety-net checks, the file moves last."""

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from strategy_runtime.runtime.abi.entry_package_errors import AbiEntryPackageTimeout
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageInternalError,
    EntryPackageResult,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.enabled_control import errors as shared
from strategy_runtime.runtime.enabled_control.cancel_step import EntryOrderCancelStep
from strategy_runtime.runtime.open_position.errors import OpenPositionLookupTimeout
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingCloseRecovery,
    PendingEntryRecovery,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.runtime.strategy_delete import errors
from strategy_runtime.runtime.strategy_delete.service import StrategyDeleteService
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
from strategy_runtime.utility.deployment_catalog import (
    TRASH_DIRECTORY_NAME,
    DeploymentTrashMover,
    FilesystemDeploymentCatalog,
    derive_strategy_instance_id,
)

RAW_SPEC = {"anchor": 500}
SID = derive_strategy_instance_id(
    strategy_id="ema_pullback", ticker="BTCUSDT.P", base_timeframe="5m", raw_spec=RAW_SPEC
)
CYCLE_ID = "cycle-1"


def spec_text(enabled: bool) -> str:
    return (
        json.dumps(
            {
                "enabled": enabled,
                "ticker": "BTCUSDT.P",
                "base_timeframe": "5m",
                "strategy_id": "ema_pullback",
                "raw_spec": RAW_SPEC,
            },
            indent=1,
        )
        + "\n"
    )


class FakeResolver:
    def __init__(
        self,
        *,
        position_open: bool = False,
        closure: TradeCycleClosure | None = None,
        error: Exception | None = None,
    ) -> None:
        self.position_open = position_open
        self.closure = closure
        self.error = error
        self.calls = 0

    def resolve(self, state: StrategyInstanceRuntimeState) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return PositionResolvedStrategyInstanceRuntimeState(
            runtime_state=state,
            position_open=self.position_open,
            first_fill_at_ms=1 if self.position_open else None,
            average_entry_price="100" if self.position_open else None,
            entry_order_link_id="link" if self.position_open else None,
            closure=None if self.position_open else self.closure,
        )


class FakeRecovery:
    def __init__(
        self, *, result: EntryPackageResult | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.cancel_calls: list[tuple[str, str, str, str]] = []

    def query(self, strategy_instance_id: str, trade_cycle_id: str) -> Any:
        raise AssertionError("query must not be called")

    def cancel(
        self, strategy_instance_id: str, trade_cycle_id: str, ticker: str, risk_multiplier: str
    ) -> EntryPackageResult:
        self.cancel_calls.append((strategy_instance_id, trade_cycle_id, ticker, risk_multiplier))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def absent() -> EntryPackageAbsent:
    return EntryPackageAbsent(strategy_instance_id=SID, trade_cycle_id=CYCLE_ID)


class Env:
    def __init__(
        self,
        tmp_path: Path,
        *,
        enabled: bool = False,
        with_state: bool = False,
        cycle: bool = False,
        pending_entry: bool = False,
        pending_close: bool = False,
        resolver: FakeResolver | None = None,
        recovery: FakeRecovery | None = None,
    ) -> None:
        self.directory = tmp_path
        self.path = tmp_path / "a.json"
        self.path.write_text(spec_text(enabled), encoding="utf-8")
        self.repository = InMemoryStrategyInstanceRuntimeStateRepository()
        if with_state:
            state = self.repository.get_or_create(
                GetOrCreateStrategyInstanceRuntimeStateRequest(
                    strategy_instance_id=SID,
                    strategy_id="ema_pullback",
                    instrument="BTCUSDT.P",
                    base_timeframe="5m",
                    raw_spec=RAW_SPEC,
                    source_path="a.json",
                )
            )
            self.repository.save(
                replace(
                    state,
                    current_trade_cycle=(
                        CurrentTradeCycle(
                            trade_cycle_id=CYCLE_ID,
                            applied_entry_package=AppliedEntryPackage(
                                applied_desired_entry=DesiredEntry(
                                    "long", 900, "100", "99", "103", "runner"
                                ),
                                calculated_quantity="0.01",
                            ),
                        )
                        if cycle
                        else None
                    ),
                    pending_entry_recovery=PendingEntryRecovery(CYCLE_ID)
                    if pending_entry
                    else None,
                    pending_close_recovery=PendingCloseRecovery(CYCLE_ID)
                    if pending_close
                    else None,
                )
            )
        self.resolver = resolver or FakeResolver()
        self.recovery = recovery or FakeRecovery(result=absent())
        self.registry = StrategyInstanceKeyedMutexRegistry()
        self.catalog = FilesystemDeploymentCatalog(tmp_path)
        self.mover = DeploymentTrashMover(self.catalog, tmp_path)
        self.service = self.build(self.mover)

    def build(self, mover: Any) -> StrategyDeleteService:
        return StrategyDeleteService(
            load_snapshot=self.catalog.load_snapshot,
            trash_mover=mover,
            cancel_step=EntryOrderCancelStep(
                state_repository=self.repository,
                open_position_resolver=self.resolver,
                abi_entry_cycle_recovery=self.recovery,
            ),
            keyed_mutex_registry=self.registry,
            mutex_wait_seconds=0.05,
        )

    @property
    def trash(self) -> list[Path]:
        directory = self.directory / TRASH_DIRECTORY_NAME
        return sorted(directory.iterdir()) if directory.exists() else []

    @property
    def state(self) -> StrategyInstanceRuntimeState | None:
        return self.repository.get(SID)


def assert_untouched(
    env: Env, original: str, state_before: StrategyInstanceRuntimeState | None
) -> None:
    assert env.path.read_text(encoding="utf-8") == original
    assert env.trash == []
    assert env.state == state_before


def test_normal_path_after_a_disable_makes_no_abi_call(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True)

    result = env.service.delete(SID)

    assert result.cancelled_entry_order is False
    assert result.trash_file.startswith(f"{TRASH_DIRECTORY_NAME}/a.")
    assert not env.path.exists() and len(env.trash) == 1
    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []


def test_strategy_without_any_state_is_deleted(tmp_path: Path) -> None:
    env = Env(tmp_path)

    env.service.delete(SID)

    assert not env.path.exists() and len(env.trash) == 1


def test_enabled_strategy_is_refused_before_any_abi_call(tmp_path: Path) -> None:
    env = Env(tmp_path, enabled=True, with_state=True, cycle=True)
    original, before = env.path.read_text(encoding="utf-8"), env.state

    with pytest.raises(errors.StillEnabled) as caught:
        env.service.delete(SID)

    assert (caught.value.status_code, caught.value.reason) == (409, "still_enabled")
    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []
    assert_untouched(env, original, before)


@pytest.mark.parametrize("which", ["entry", "close"])
def test_recovery_pending_is_refused_without_abi_call(tmp_path: Path, which: str) -> None:
    env = Env(
        tmp_path,
        with_state=True,
        cycle=which == "close",
        pending_entry=which == "entry",
        pending_close=which == "close",
    )
    original, before = env.path.read_text(encoding="utf-8"), env.state

    with pytest.raises(shared.RecoveryPending):
        env.service.delete(SID)

    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []
    assert_untouched(env, original, before)


def test_open_position_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True, cycle=True, resolver=FakeResolver(position_open=True))
    original, before = env.path.read_text(encoding="utf-8"), env.state

    with pytest.raises(shared.PositionOpen):
        env.service.delete(SID)

    assert env.recovery.cancel_calls == []
    assert_untouched(env, original, before)


def test_detected_closure_is_refused(tmp_path: Path) -> None:
    closure = TradeCycleClosure(
        strategy_instance_id=SID,
        trade_cycle_id=CYCLE_ID,
        reason="stop_loss",
        order_id="o1",
        order_link_id=None,
        parent_order_link_id="parent-link",
    )
    env = Env(tmp_path, with_state=True, cycle=True, resolver=FakeResolver(closure=closure))
    original, before = env.path.read_text(encoding="utf-8"), env.state

    with pytest.raises(shared.CycleNotSettled):
        env.service.delete(SID)

    assert env.recovery.cancel_calls == []
    assert_untouched(env, original, before)


def test_resting_entry_order_is_cancelled_then_the_file_moves(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True, cycle=True)

    result = env.service.delete(SID)

    assert result.cancelled_entry_order is True
    assert len(env.recovery.cancel_calls) == 1
    assert env.state is not None and env.state.current_trade_cycle is None
    assert not env.path.exists() and len(env.trash) == 1


def test_cancel_not_confirmed_leaves_state_and_file(tmp_path: Path) -> None:
    env = Env(
        tmp_path,
        with_state=True,
        cycle=True,
        recovery=FakeRecovery(result=EntryPackageInternalError(message="boom")),
    )
    original, before = env.path.read_text(encoding="utf-8"), env.state

    with pytest.raises(shared.CancelNotConfirmed):
        env.service.delete(SID)

    assert_untouched(env, original, before)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resolver": FakeResolver(error=OpenPositionLookupTimeout("t"))},
        {"recovery": FakeRecovery(error=AbiEntryPackageTimeout())},
    ],
)
def test_abi_error_is_refused_and_nothing_changes(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    env = Env(tmp_path, with_state=True, cycle=True, **kwargs)
    original, before = env.path.read_text(encoding="utf-8"), env.state

    with pytest.raises(shared.AbiUnavailable):
        env.service.delete(SID)

    assert_untouched(env, original, before)


def test_unknown_instance_is_404_and_creates_no_mutex_entry(tmp_path: Path) -> None:
    env = Env(tmp_path)

    with pytest.raises(shared.StrategyInstanceNotFound):
        env.service.delete("ema_pullback:" + "0" * 24)

    assert env.registry._locks == {}  # noqa: SLF001


def test_second_delete_of_the_same_id_is_404_and_state_record_stays(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True)
    env.service.delete(SID)

    with pytest.raises(shared.StrategyInstanceNotFound):
        env.service.delete(SID)

    assert env.state is not None
    assert env.catalog.load_snapshot().get_by_strategy_instance_id(SID) is None


def test_busy_instance_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True)
    original, before = env.path.read_text(encoding="utf-8"), env.state
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with env.registry.hold(SID):
            held.set()
            release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    held.wait(2)
    try:
        with pytest.raises(shared.InstanceBusy):
            env.service.delete(SID)
    finally:
        release.set()
        thread.join()

    assert_untouched(env, original, before)


def test_file_changed_during_the_cancel_keeps_the_file_and_the_cleared_state(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path, with_state=True, cycle=True)
    original_cancel = env.recovery.cancel

    def cancel_and_edit(*args: str) -> EntryPackageResult:
        result = original_cancel(*args)
        env.path.write_text(spec_text(False).replace('"anchor"', '"anchor" '), encoding="utf-8")
        return result

    env.recovery.cancel = cancel_and_edit  # type: ignore[method-assign]

    with pytest.raises(shared.FileChanged):
        env.service.delete(SID)

    assert env.path.exists() and env.trash == []
    assert env.state is not None and env.state.current_trade_cycle is None
    # a retry is idempotent and makes no further ABI call
    env.service.delete(SID)
    assert len(env.recovery.cancel_calls) == 1 and len(env.trash) == 1


class BrokenMover:
    def __init__(self, inner: DeploymentTrashMover, error: Exception) -> None:
        self.inner = inner
        self.error = error

    def read_original(self, strategy_instance_id: str) -> bytes:
        return self.inner.read_original(strategy_instance_id)

    def move_to_trash(self, strategy_instance_id: str, original: bytes) -> str:
        raise self.error


@pytest.mark.parametrize(
    ("error_name", "expected"),
    [
        ("DeploymentTrashMoveFailed", errors.MoveFailed),
        ("DeploymentTrashNameTaken", errors.TrashNameTaken),
    ],
)
def test_failed_move_after_a_cancel_keeps_the_file_and_a_retry_calls_no_abi(
    tmp_path: Path, error_name: str, expected: type[Exception]
) -> None:
    from strategy_runtime.utility import deployment_catalog

    env = Env(tmp_path, with_state=True, cycle=True)
    broken = env.build(BrokenMover(env.mover, getattr(deployment_catalog, error_name)("x")))
    original = env.path.read_text(encoding="utf-8")

    with pytest.raises(expected):
        broken.delete(SID)

    assert env.path.read_text(encoding="utf-8") == original and env.trash == []
    assert env.state is not None and env.state.current_trade_cycle is None
    env.service.delete(SID)
    assert len(env.recovery.cancel_calls) == 1 and len(env.trash) == 1


def test_delete_does_not_change_the_state_store_otherwise(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True)
    before = env.state

    env.service.delete(SID)

    assert env.state == before
