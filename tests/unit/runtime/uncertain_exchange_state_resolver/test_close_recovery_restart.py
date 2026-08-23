"""Restart/replay regression for `pending_close_recovery` (correction pass
item 5): a durable close marker survives a process restart (a fresh
`JsonlStrategyInstanceRuntimeStateRepository` against the same file), the
worker/resolver still discovers and resolves it, and the resulting durable
state survives a second reload -- not just an in-memory object mutation."""

from pathlib import Path

from strategy_runtime.infrastructure.runtime_state import (
    JsonlStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.position_management_execution.models import (
    ClosePositionCommand,
    PositionClosedConfirmation,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingCloseRecovery,
)
from strategy_runtime.runtime.uncertain_exchange_state_resolver.resolver import (
    UncertainExchangeStateResolver,
)

_SID = "ema_pullback:abc"


class _NoOpEntryCycleRecoveryPort:
    def query(self, strategy_instance_id: str, trade_cycle_id: str) -> None:  # pragma: no cover
        raise AssertionError("entry-cycle recovery must not be queried for close recovery")

    def cancel(
        self, strategy_instance_id: str, trade_cycle_id: str, ticker: str, risk_multiplier: str
    ) -> None:  # pragma: no cover
        raise AssertionError("entry-cycle recovery must not be queried for close recovery")


class _FakeClosePort:
    def __init__(self, confirmation: PositionClosedConfirmation) -> None:
        self._confirmation = confirmation
        self.close_calls: list[ClosePositionCommand] = []

    def apply_protection(self, command: object) -> object:  # pragma: no cover - unused
        raise NotImplementedError

    def close_position(self, command: ClosePositionCommand) -> PositionClosedConfirmation:
        self.close_calls.append(command)
        return self._confirmation


def test_pending_close_recovery_survives_restart_and_resolves_durably(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"

    # --- process 1: register, then durably pre-write pending_close_recovery,
    # simulating PositionManagementOrchestrator's pre-write before an
    # in-flight close_position call whose response never arrived.
    first_process_repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=_SID,
        strategy_id="ema_pullback",
        instrument="BTCUSDT.P",
        base_timeframe="5m",
        raw_spec={"ema": 200},
        source_path="ema-pullback.json",
    )
    state = first_process_repository.get_or_create(request)
    cycle = CurrentTradeCycle(
        "cycle-1",
        AppliedEntryPackage(
            applied_desired_entry=DesiredEntry("long", 900, "100", "99", "103", "runner"),
            calculated_quantity="0.01",
        ),
    )
    from dataclasses import replace

    state = first_process_repository.save(
        replace(
            state,
            current_trade_cycle=cycle,
            pending_close_recovery=PendingCloseRecovery("cycle-1"),
        )
    )
    assert state.pending_close_recovery is not None

    # --- restart: a brand-new repository instance replays the same file,
    # exactly as happens on process restart -- not the same Python object.
    restarted_repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    replayed = restarted_repository.get(_SID)
    assert replayed is not None
    assert replayed.current_trade_cycle is not None
    assert replayed.pending_close_recovery == PendingCloseRecovery("cycle-1")

    # --- worker/resolver discovers the replayed marker and resolves it.
    assert restarted_repository.list_ids_with_pending_close_recovery() == (_SID,)
    close_port = _FakeClosePort(PositionClosedConfirmation(_SID, "cycle-1"))
    resolver = UncertainExchangeStateResolver(
        state_repository=restarted_repository,
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        abi_entry_cycle_recovery=_NoOpEntryCycleRecoveryPort(),  # type: ignore[arg-type]
        position_management_execution=close_port,  # type: ignore[arg-type]
    )

    resolver.attempt(_SID)

    assert len(close_port.close_calls) == 1
    resolved = restarted_repository.get(_SID)
    assert resolved is not None
    assert resolved.current_trade_cycle is None
    assert resolved.pending_close_recovery is None
    assert restarted_repository.list_ids_with_pending_close_recovery() == ()

    # --- a second reload (another restart) confirms the same durable fact,
    # not just an in-memory mutation on the still-live repository object.
    second_restart_repository = JsonlStrategyInstanceRuntimeStateRepository(path)
    reloaded = second_restart_repository.get(_SID)
    assert reloaded is not None
    assert reloaded.current_trade_cycle is None
    assert reloaded.pending_close_recovery is None
    assert second_restart_repository.list_ids_with_pending_close_recovery() == ()
