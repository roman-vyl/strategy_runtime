"""`StrategyOperatorCommandsService`: close-position and cancel-entry-orders decision tables."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from enabled_control.test_service import (
    CYCLE_ID,
    SID,
    Env,
    FakeEndedJournal,
    FakeRecovery,
    FakeResolver,
    absent,
)

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.enabled_control import errors
from strategy_runtime.runtime.enabled_control.cancel_step import EntryOrderCancelStep
from strategy_runtime.runtime.operator_commands import StrategyOperatorCommandsService
from strategy_runtime.runtime.position_management_execution import (
    ClosePositionCommand,
    PositionClosedConfirmation,
)
from strategy_runtime.runtime.position_management_execution.errors import (
    PositionManagementExecutionError,
)
from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure
from strategy_runtime.utility.deployment_catalog import (
    DeploymentEnabledFileWriter,
    FilesystemDeploymentCatalog,
)


class FakeExecution:
    def __init__(self, env: "CmdEnv", *, error: Exception | None = None, closure: bool = True):
        self.env = env
        self.error = error
        self.closure = closure
        self.commands: list[ClosePositionCommand] = []
        self.seen_marker: list[bool] = []
        self.seen_file_enabled: list[bool] = []

    def close_position(self, command: ClosePositionCommand) -> PositionClosedConfirmation:
        self.commands.append(command)
        state = self.env.state
        self.seen_marker.append(state is not None and state.pending_close_recovery is not None)
        self.seen_file_enabled.append(self.env.file_enabled)
        if self.error is not None:
            raise self.error
        closure = (
            TradeCycleClosure(
                strategy_instance_id=command.strategy_instance_id,
                trade_cycle_id=command.trade_cycle_id,
                reason="runtime_signal",
                order_id="o1",
                order_link_id="l1",
                parent_order_link_id=None,
            )
            if self.closure
            else None
        )
        return PositionClosedConfirmation(
            command.strategy_instance_id, command.trade_cycle_id, closure
        )


class FakeClosedJournal:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def trade_cycle_closed(self, **fields: Any) -> None:
        self.calls.append(fields)


class CmdEnv(Env):
    def __init__(
        self,
        tmp_path: Path,
        *,
        execution_error: Exception | None = None,
        wait: float = 0.05,
        **kwargs: Any,
    ) -> None:
        super().__init__(tmp_path, **kwargs)
        self.execution = FakeExecution(self, error=execution_error)
        self.ended = FakeEndedJournal()
        catalog = FilesystemDeploymentCatalog(tmp_path)
        self.commands = StrategyOperatorCommandsService(
            load_snapshot=catalog.load_snapshot,
            enabled_writer=DeploymentEnabledFileWriter(catalog, tmp_path),
            state_repository=self.repository,
            open_position_resolver=self.resolver,
            position_management_execution=self.execution,  # type: ignore[arg-type]
            cancel_step=EntryOrderCancelStep(
                state_repository=self.repository,
                open_position_resolver=self.resolver,
                abi_entry_cycle_recovery=self.recovery,
                entry_cycle_ended_journal=self.ended,
            ),
            keyed_mutex_registry=self.registry,
            mutex_wait_seconds=wait,
        )


class FilledResolver(FakeResolver):
    def resolve(self, state: Any) -> Any:
        resolved = super().resolve(state)
        return replace(resolved, first_fill_at_ms=1_000_000) if resolved.position_open else resolved


def open_env(tmp_path: Path, **kwargs: Any) -> CmdEnv:
    return CmdEnv(
        tmp_path, with_state=True, cycle=True, resolver=FilledResolver(position_open=True), **kwargs
    )


def test_close_writes_disabled_and_marker_before_the_exchange_call(tmp_path: Path) -> None:
    env = open_env(tmp_path)

    result = env.commands.close_position(SID)

    assert (result.enabled, result.trade_cycle_id, result.closure_reason) == (
        False,
        CYCLE_ID,
        "runtime_signal",
    )
    assert env.execution.commands == [ClosePositionCommand(SID, CYCLE_ID)]
    assert env.execution.seen_marker == [True]
    assert env.execution.seen_file_enabled == [False]
    assert env.file_enabled is False
    state = env.state
    assert state is not None
    assert state.current_trade_cycle is None and state.pending_close_recovery is None


def test_close_freezes_a_first_fill_the_bar_has_not_frozen(tmp_path: Path) -> None:
    env = open_env(tmp_path)
    assert env.state is not None and env.state.current_trade_cycle is not None
    assert env.state.current_trade_cycle.frozen_entry_context is None

    env.commands.close_position(SID)

    assert env.execution.commands  # reached the exchange after freezing


def test_close_not_confirmed_leaves_marker_and_disabled(tmp_path: Path) -> None:
    env = open_env(tmp_path, execution_error=PositionManagementExecutionError("x"))

    with pytest.raises(errors.AbiUnavailable) as raised:
        env.commands.close_position(SID)

    assert (raised.value.status_code, raised.value.reason) == (502, "abi_unavailable")
    assert env.file_enabled is False
    state = env.state
    assert state is not None
    assert state.pending_close_recovery is not None and state.current_trade_cycle is not None


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"with_state": False}, "no_position"),
        ({"with_state": True}, "no_position"),
        ({"with_state": True, "cycle": True}, "no_position"),
        ({"with_state": True, "cycle": True, "pending_close": True}, "recovery_pending"),
        ({"with_state": True, "cycle": True, "pending_entry": True}, "recovery_pending"),
    ],
)
def test_close_refusals_change_nothing(tmp_path: Path, kwargs: dict[str, Any], reason: str) -> None:
    env = CmdEnv(tmp_path, **kwargs)

    with pytest.raises(errors.EnabledControlRefused) as raised:
        env.commands.close_position(SID)

    assert (raised.value.status_code, raised.value.reason) == (409, reason)
    assert env.file_enabled is True
    assert env.execution.commands == []


def test_close_refuses_when_cycle_is_already_settled(tmp_path: Path) -> None:
    closure = TradeCycleClosure(SID, CYCLE_ID, "runtime_signal", "o", "l", None)
    env = CmdEnv(
        tmp_path,
        with_state=True,
        cycle=True,
        resolver=FakeResolver(position_open=False, closure=closure),
    )

    with pytest.raises(errors.CycleNotSettled):
        env.commands.close_position(SID)

    assert env.file_enabled is True and env.execution.commands == []


def test_close_abi_lookup_failure_is_502_without_changes(tmp_path: Path) -> None:
    from strategy_runtime.runtime.open_position.errors import OpenPositionLookupTimeout

    env = CmdEnv(
        tmp_path,
        with_state=True,
        cycle=True,
        resolver=FakeResolver(error=OpenPositionLookupTimeout("t")),
    )

    with pytest.raises(errors.AbiUnavailable):
        env.commands.close_position(SID)

    assert env.file_enabled is True and env.execution.commands == []


def test_unknown_instance_is_404_before_taking_the_mutex(tmp_path: Path) -> None:
    env = CmdEnv(tmp_path)

    for call in (env.commands.close_position, env.commands.cancel_entry_orders):
        with pytest.raises(errors.StrategyInstanceNotFound):
            call("unknown")
    assert isinstance(env.registry, StrategyInstanceKeyedMutexRegistry)


def test_busy_instance_is_503(tmp_path: Path) -> None:
    env = open_env(tmp_path)

    with env.registry.hold(SID, timeout_seconds=1.0):
        with pytest.raises(errors.InstanceBusy):
            env.commands.close_position(SID)
        with pytest.raises(errors.InstanceBusy):
            env.commands.cancel_entry_orders(SID)

    assert env.file_enabled is True


def test_cancel_clears_the_cycle_and_disables(tmp_path: Path) -> None:
    env = CmdEnv(tmp_path, with_state=True, cycle=True)

    result = env.commands.cancel_entry_orders(SID)

    assert (result.enabled, result.cancelled_entry_order) == (False, True)
    assert env.file_enabled is False
    assert env.state is not None and env.state.current_trade_cycle is None
    assert [c["reason"] for c in env.ended.calls] == ["disabled"]


def test_cancel_with_nothing_pending_still_disables(tmp_path: Path) -> None:
    env = CmdEnv(tmp_path)

    result = env.commands.cancel_entry_orders(SID)

    assert (result.enabled, result.cancelled_entry_order) == (False, False)
    assert env.file_enabled is False


def test_cancel_runs_even_when_the_file_is_already_disabled(tmp_path: Path) -> None:
    env = CmdEnv(tmp_path, enabled=False, with_state=True, cycle=True)

    result = env.commands.cancel_entry_orders(SID)

    assert result.cancelled_entry_order is True
    assert env.recovery.cancel_calls == [(SID, CYCLE_ID, "BTCUSDT.P", "1")]


def test_cancel_with_position_open_is_refused(tmp_path: Path) -> None:
    env = open_env(tmp_path)

    with pytest.raises(errors.PositionOpen):
        env.commands.cancel_entry_orders(SID)

    assert env.file_enabled is True


def test_cancel_not_confirmed_leaves_everything(tmp_path: Path) -> None:
    env = CmdEnv(
        tmp_path, with_state=True, cycle=True, recovery=FakeRecovery(result=absent("other"))
    )

    with pytest.raises(errors.CancelNotConfirmed):
        env.commands.cancel_entry_orders(SID)

    assert env.file_enabled is True
    assert env.state is not None and env.state.current_trade_cycle is not None
