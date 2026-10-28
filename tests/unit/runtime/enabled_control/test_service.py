"""`StrategyEnabledControlService`: the disable decision table and the write-last order."""

import contextlib
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
from strategy_runtime.runtime.enabled_control import errors
from strategy_runtime.runtime.enabled_control.service import StrategyEnabledControlService
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
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
from strategy_runtime.utility.deployment_catalog import (
    DeploymentEnabledFileWriter,
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
        if self.position_open:
            return PositionResolvedStrategyInstanceRuntimeState(
                runtime_state=state,
                position_open=True,
                first_fill_at_ms=1,
                average_entry_price="100",
                entry_order_link_id="link",
            )
        return PositionResolvedStrategyInstanceRuntimeState(
            runtime_state=state,
            position_open=False,
            first_fill_at_ms=None,
            average_entry_price=None,
            closure=self.closure,
        )


class FakeRecovery:
    def __init__(
        self,
        *,
        result: EntryPackageResult | None = None,
        error: Exception | None = None,
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


def absent(cycle_id: str = CYCLE_ID, sid: str = SID) -> EntryPackageAbsent:
    return EntryPackageAbsent(strategy_instance_id=sid, trade_cycle_id=cycle_id)


class Env:
    def __init__(
        self,
        tmp_path: Path,
        *,
        enabled: bool = True,
        with_state: bool = False,
        cycle: bool = False,
        pending_entry: bool = False,
        pending_close: bool = False,
        resolver: FakeResolver | None = None,
        recovery: FakeRecovery | None = None,
        journal: Any = None,
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
        catalog = FilesystemDeploymentCatalog(tmp_path)
        self.service = StrategyEnabledControlService(
            load_snapshot=catalog.load_snapshot,
            enabled_writer=DeploymentEnabledFileWriter(catalog, tmp_path),
            state_repository=self.repository,
            open_position_resolver=self.resolver,
            abi_entry_cycle_recovery=self.recovery,
            keyed_mutex_registry=self.registry,
            mutex_wait_seconds=0.05,
            entry_cycle_ended_journal=journal,
        )

    @property
    def file_enabled(self) -> bool:
        return bool(json.loads(self.path.read_text(encoding="utf-8"))["enabled"])

    @property
    def state(self) -> StrategyInstanceRuntimeState | None:
        return self.repository.get(SID)


class FakeEndedJournal:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def entry_cycle_ended(self, **fields: object) -> None:
        self.calls.append(fields)


def test_disable_that_cancels_the_entry_order_journals_the_ended_cycle(tmp_path: Path) -> None:
    journal = FakeEndedJournal()
    env = Env(tmp_path, with_state=True, cycle=True, journal=journal)

    env.service.set_enabled(SID, False)

    assert journal.calls == [
        {
            "strategy_instance_id": SID,
            "trade_cycle_id": CYCLE_ID,
            "bar_open_time_ms": None,
            "reason": "disabled",
        }
    ]
    assert env.state is not None and env.state.current_trade_cycle is None


@pytest.mark.parametrize(
    "env_kwargs",
    [
        {"with_state": True},
        {"with_state": True, "cycle": True, "resolver": FakeResolver(position_open=True)},
        {"with_state": True, "cycle": True, "recovery": FakeRecovery(result=absent("other"))},
        {"with_state": True, "cycle": True, "pending_entry": True},
    ],
)
def test_disable_without_a_cancelled_entry_journals_nothing(
    tmp_path: Path, env_kwargs: dict[str, Any]
) -> None:
    journal = FakeEndedJournal()
    env = Env(tmp_path, journal=journal, **env_kwargs)

    with contextlib.suppress(errors.EnabledControlRefused):
        env.service.set_enabled(SID, False)

    assert journal.calls == []


def test_disable_with_nothing_open_writes_the_file(tmp_path: Path) -> None:
    env = Env(tmp_path)

    result = env.service.set_enabled(SID, False)

    assert (result.enabled, result.cancelled_entry_order) == (False, False)
    assert env.file_enabled is False
    assert env.resolver.calls == 0


def test_disable_with_state_but_no_cycle_makes_no_abi_call(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True)

    env.service.set_enabled(SID, False)

    assert env.file_enabled is False
    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []


def test_enable_writes_the_file_without_any_abi_call(tmp_path: Path) -> None:
    env = Env(tmp_path, enabled=False, with_state=True, cycle=True)

    result = env.service.set_enabled(SID, True)

    assert (result.enabled, result.cancelled_entry_order) == (True, False)
    assert env.file_enabled is True
    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []


@pytest.mark.parametrize("enabled", [True, False])
def test_already_in_requested_state_writes_nothing_and_calls_no_abi(
    tmp_path: Path, enabled: bool
) -> None:
    env = Env(tmp_path, enabled=enabled, with_state=True, cycle=True)
    before = env.path.stat().st_mtime_ns

    result = env.service.set_enabled(SID, enabled)

    assert result.enabled is enabled and result.cancelled_entry_order is False
    assert env.path.stat().st_mtime_ns == before
    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []


def test_entry_order_is_cancelled_state_cleared_then_file_written(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True, cycle=True)
    order: list[str] = []
    real_save = env.repository.save
    real_set = env.service._enabled_writer.set_enabled  # noqa: SLF001

    def save(state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        order.append("state_saved")
        return real_save(state)

    def set_enabled(sid: str, enabled: bool) -> bool:
        order.append("file_written")
        return real_set(sid, enabled)

    env.repository.save = save  # type: ignore[method-assign]
    env.service._enabled_writer.set_enabled = set_enabled  # type: ignore[method-assign]  # noqa: SLF001

    result = env.service.set_enabled(SID, False)

    assert result.cancelled_entry_order is True
    assert env.recovery.cancel_calls == [(SID, CYCLE_ID, "BTCUSDT.P", "1")]
    assert order == ["state_saved", "file_written"]
    assert env.state is not None and env.state.current_trade_cycle is None
    assert env.file_enabled is False


def test_position_open_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True, cycle=True, resolver=FakeResolver(position_open=True))

    with pytest.raises(errors.PositionOpen) as raised:
        env.service.set_enabled(SID, False)

    assert (raised.value.status_code, raised.value.reason) == (409, "position_open")
    assert env.file_enabled is True
    assert env.state is not None and env.state.current_trade_cycle is not None
    assert env.recovery.cancel_calls == []


@pytest.mark.parametrize("marker", ["pending_entry", "pending_close"])
def test_recovery_pending_is_refused_without_any_abi_call(tmp_path: Path, marker: str) -> None:
    env = Env(
        tmp_path,
        with_state=True,
        cycle=True,
        pending_entry=marker == "pending_entry",
        pending_close=marker == "pending_close",
    )

    with pytest.raises(errors.RecoveryPending) as raised:
        env.service.set_enabled(SID, False)

    assert (raised.value.status_code, raised.value.reason) == (409, "recovery_pending")
    assert env.file_enabled is True
    assert env.resolver.calls == 0 and env.recovery.cancel_calls == []


def test_detected_closure_is_refused_and_not_applied(tmp_path: Path) -> None:
    closure = TradeCycleClosure(
        strategy_instance_id=SID,
        trade_cycle_id=CYCLE_ID,
        reason="stop_loss",
        order_id="o1",
        order_link_id=None,
        parent_order_link_id="parent-link",
    )
    env = Env(tmp_path, with_state=True, cycle=True, resolver=FakeResolver(closure=closure))

    with pytest.raises(errors.CycleNotSettled) as raised:
        env.service.set_enabled(SID, False)

    assert (raised.value.status_code, raised.value.reason) == (409, "cycle_not_settled")
    assert env.file_enabled is True
    assert env.state is not None and env.state.current_trade_cycle is not None
    assert env.recovery.cancel_calls == []


@pytest.mark.parametrize(
    "result",
    [
        EntryPackageInternalError(message="boom"),
        absent(cycle_id="other-cycle"),
        absent(sid="ema_pullback:other"),
    ],
)
def test_cancel_not_confirmed_leaves_state_and_file_unchanged(
    tmp_path: Path, result: EntryPackageResult
) -> None:
    env = Env(tmp_path, with_state=True, cycle=True, recovery=FakeRecovery(result=result))

    with pytest.raises(errors.CancelNotConfirmed) as raised:
        env.service.set_enabled(SID, False)

    assert (raised.value.status_code, raised.value.reason) == (409, "cancel_not_confirmed")
    assert env.file_enabled is True
    assert env.state is not None and env.state.current_trade_cycle is not None


def test_abi_error_during_resolve_changes_nothing(tmp_path: Path) -> None:
    env = Env(
        tmp_path,
        with_state=True,
        cycle=True,
        resolver=FakeResolver(error=OpenPositionLookupTimeout()),
    )

    with pytest.raises(errors.AbiUnavailable) as raised:
        env.service.set_enabled(SID, False)

    assert (raised.value.status_code, raised.value.reason) == (502, "abi_unavailable")
    assert env.file_enabled is True and env.recovery.cancel_calls == []


def test_abi_error_during_cancel_changes_nothing(tmp_path: Path) -> None:
    env = Env(
        tmp_path,
        with_state=True,
        cycle=True,
        recovery=FakeRecovery(error=AbiEntryPackageTimeout()),
    )

    with pytest.raises(errors.AbiUnavailable):
        env.service.set_enabled(SID, False)

    assert env.file_enabled is True
    assert env.state is not None and env.state.current_trade_cycle is not None


def test_file_write_failure_after_cancel_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Env(tmp_path, with_state=True, cycle=True)
    failures = iter([OSError("disk full")])
    import strategy_runtime.utility.deployment_catalog.enabled_writer as writer_module

    real_replace = writer_module.os.replace

    def flaky_replace(source: Any, destination: Any) -> None:
        error = next(failures, None)
        if error is not None:
            raise error
        real_replace(source, destination)

    monkeypatch.setattr(writer_module.os, "replace", flaky_replace)

    with pytest.raises(errors.WriteFailed) as raised:
        env.service.set_enabled(SID, False)
    assert (raised.value.status_code, raised.value.reason) == (500, "write_failed")
    assert env.file_enabled is True
    assert env.state is not None and env.state.current_trade_cycle is None  # order is gone

    result = env.service.set_enabled(SID, False)  # idempotent retry
    assert result.cancelled_entry_order is False
    assert env.file_enabled is False


def test_unknown_instance_is_404_and_never_reaches_the_mutex(tmp_path: Path) -> None:
    env = Env(tmp_path)

    with pytest.raises(errors.StrategyInstanceNotFound) as raised:
        env.service.set_enabled("ema_pullback:unknown", False)

    assert raised.value.status_code == 404
    assert env.registry._locks == {}  # noqa: SLF001


def test_busy_instance_is_503_after_the_wait_and_changes_nothing(tmp_path: Path) -> None:
    env = Env(tmp_path, with_state=True, cycle=True)
    entered = threading.Event()
    release = threading.Event()

    def hold_instance() -> None:
        with env.registry.hold(SID):
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=hold_instance)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(errors.InstanceBusy) as raised:
            env.service.set_enabled(SID, False)
        assert (raised.value.status_code, raised.value.reason) == (503, "instance_busy")
    finally:
        release.set()
        thread.join()

    assert env.file_enabled is True
    assert env.recovery.cancel_calls == []


def test_file_changed_by_hand_during_the_change_is_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Env(tmp_path)
    import strategy_runtime.utility.deployment_catalog.enabled_writer as writer_module

    real_open = writer_module.os.open

    def editing_open(target: Any, flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(target, flags, mode)
        if ".tmp-" in str(target):
            env.path.write_text(spec_text(True) + " ", encoding="utf-8")
        return descriptor

    monkeypatch.setattr(writer_module.os, "open", editing_open)

    with pytest.raises(errors.FileChanged) as raised:
        env.service.set_enabled(SID, False)

    assert (raised.value.status_code, raised.value.reason) == (409, "file_changed")
    assert env.file_enabled is True
