"""`UncertainExchangeStateResolver.attempt(...)`: the resolution table from
design.md Decision 5, plus the shared-mutex and no-wall-clock-gate guarantees."""

from dataclasses import replace

import pytest

from strategy_runtime.runtime.abi.entry_cycle_recovery_errors import (
    AbiEntryCycleRecoveryUnavailable,
    AbiEntryCycleRecoveryUnknownTradeCycleBinding,
)
from strategy_runtime.runtime.abi.entry_cycle_recovery_models import (
    EntryOrderLiveRecoveryState,
    PositionOpenRecoveryState,
    RecoveryStateAppliedEntryPackage,
    RecoveryStateResponse,
    TerminalAfterFillRecoveryState,
    TerminalWithoutFillRecoveryState,
)
from strategy_runtime.runtime.abi.entry_package_errors import (
    AbiEntryPackageNetworkFailure,
    AbiEntryPackageProtocolError,
    AbiEntryPackageTimeout,
)
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageApplied,
    EntryPackageInternalError,
    EntryPackageResult,
    EntryPackageWireDesiredEntry,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    PendingEntryRecovery,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.runtime.uncertain_exchange_state_resolver.resolver import (
    UncertainExchangeStateResolver,
)

_SID = "ema_pullback:abc"


def desired_entry() -> DesiredEntry:
    return DesiredEntry("long", 900, "100", "99", "103", "runner")


def wire_desired_entry() -> EntryPackageWireDesiredEntry:
    return EntryPackageWireDesiredEntry("long", 900, "100", "99", "103", "runner")


def applied_entry_package() -> RecoveryStateAppliedEntryPackage:
    return RecoveryStateAppliedEntryPackage(
        applied_desired_entry=wire_desired_entry(), calculated_quantity="0.01"
    )


class FakeAbiEntryCycleRecoveryPort:
    def __init__(
        self,
        *,
        query_result: RecoveryStateResponse | None = None,
        query_error: Exception | None = None,
        cancel_result: EntryPackageResult | None = None,
        cancel_error: Exception | None = None,
    ) -> None:
        self.query_result = query_result
        self.query_error = query_error
        self.cancel_result = cancel_result
        self.cancel_error = cancel_error
        self.query_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[tuple[str, str, str, str]] = []

    def query(self, strategy_instance_id: str, trade_cycle_id: str) -> RecoveryStateResponse:
        self.query_calls.append((strategy_instance_id, trade_cycle_id))
        if self.query_error is not None:
            raise self.query_error
        assert self.query_result is not None
        return self.query_result

    def cancel(
        self,
        strategy_instance_id: str,
        trade_cycle_id: str,
        ticker: str,
        risk_multiplier: str,
    ) -> EntryPackageResult:
        self.cancel_calls.append((strategy_instance_id, trade_cycle_id, ticker, risk_multiplier))
        if self.cancel_error is not None:
            raise self.cancel_error
        assert self.cancel_result is not None
        return self.cancel_result


def _repository_with_state(
    *,
    current_trade_cycle: CurrentTradeCycle | None = None,
    pending_entry_recovery: PendingEntryRecovery | None,
) -> tuple[InMemoryStrategyInstanceRuntimeStateRepository, StrategyInstanceRuntimeState]:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    state = repository.get_or_create(
        GetOrCreateStrategyInstanceRuntimeStateRequest(
            strategy_instance_id=_SID,
            strategy_id="ema_pullback",
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={},
            source_path="a.json",
        )
    )
    state = repository.save(
        replace(
            state,
            current_trade_cycle=current_trade_cycle,
            pending_entry_recovery=pending_entry_recovery,
        )
    )
    return repository, state


def _make_resolver(
    repository: InMemoryStrategyInstanceRuntimeStateRepository,
    port: FakeAbiEntryCycleRecoveryPort,
) -> UncertainExchangeStateResolver:
    return UncertainExchangeStateResolver(
        state_repository=repository,
        keyed_mutex_registry=StrategyInstanceKeyedMutexRegistry(),
        abi_entry_cycle_recovery=port,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# No pending marker: no ABI call.
# ---------------------------------------------------------------------------


def test_attempt_is_a_no_op_when_nothing_is_pending() -> None:
    repository, _state = _repository_with_state(pending_entry_recovery=None)
    port = FakeAbiEntryCycleRecoveryPort()
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    assert port.query_calls == []


def test_attempt_is_a_no_op_when_the_instance_is_unregistered() -> None:
    repository = InMemoryStrategyInstanceRuntimeStateRepository()
    port = FakeAbiEntryCycleRecoveryPort()
    resolver = _make_resolver(repository, port)

    resolver.attempt("missing")

    assert port.query_calls == []


# ---------------------------------------------------------------------------
# Uncertain Apply (current_trade_cycle is None): the four positive states.
# ---------------------------------------------------------------------------


def test_uncertain_apply_entry_order_live_reconstructs_the_cycle() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package())
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.pending_entry_recovery is None
    assert result.current_trade_cycle == CurrentTradeCycle(
        "cycle-new",
        AppliedEntryPackage(desired_entry(), "0.01"),
    )
    assert result.current_trade_cycle.frozen_entry_context is None
    assert port.cancel_calls == []


def test_uncertain_apply_position_open_reconstructs_the_cycle_and_freezes_first_fill() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=PositionOpenRecoveryState(
            applied_entry_package=applied_entry_package(),
            first_fill_at_ms=1_000_000,
            average_entry_price="100",
        )
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.pending_entry_recovery is None
    assert result.current_trade_cycle is not None
    assert result.current_trade_cycle.trade_cycle_id == "cycle-new"
    assert result.current_trade_cycle.frozen_entry_context is not None
    assert result.current_trade_cycle.frozen_entry_context.first_fill_at_ms == 1_000_000


def test_uncertain_apply_terminal_without_fill_forgets_the_attempt() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    port = FakeAbiEntryCycleRecoveryPort(query_result=TerminalWithoutFillRecoveryState())
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None


def test_uncertain_apply_terminal_after_fill_forgets_the_attempt() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    port = FakeAbiEntryCycleRecoveryPort(query_result=TerminalAfterFillRecoveryState())
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None


# ---------------------------------------------------------------------------
# Uncertain removal (current_trade_cycle == A): the four positive states,
# with entry_order_live triggering the one corrective action.
# ---------------------------------------------------------------------------


def _existing_cycle() -> CurrentTradeCycle:
    return CurrentTradeCycle("cycle-1", AppliedEntryPackage(desired_entry(), "0.01"))


def test_uncertain_removal_terminal_without_fill_confirms_the_removal() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(query_result=TerminalWithoutFillRecoveryState())
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None


def test_uncertain_removal_terminal_after_fill_confirms_the_removal() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(query_result=TerminalAfterFillRecoveryState())
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None


def test_uncertain_removal_position_open_means_the_removal_lost_the_race() -> None:
    existing = _existing_cycle()
    repository, _ = _repository_with_state(
        current_trade_cycle=existing,
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=PositionOpenRecoveryState(
            applied_entry_package=applied_entry_package(),
            first_fill_at_ms=1_000_000,
            average_entry_price="100",
        )
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.pending_entry_recovery is None
    # current_trade_cycle is left exactly as it was -- no reversal, no cancel,
    # no first-fill freeze performed by the resolver itself.
    assert result.current_trade_cycle == existing
    assert port.cancel_calls == []


def test_uncertain_removal_entry_order_live_issues_the_one_corrective_cancel() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package()),
        cancel_result=EntryPackageAbsent("ema_pullback:abc", "cycle-1"),
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    assert port.cancel_calls == [("ema_pullback:abc", "cycle-1", "BTCUSDT.P", "1")]


# ---------------------------------------------------------------------------
# The cross-service composition fix: ABI's entry-package PUT clears
# order_link_id to null on a confirmed absent result, after which ABI's
# recovery-state GET fails safe (500) for that trade cycle forever. Waiting
# for a later recovery-state observation to confirm the same fact the
# corrective cancel itself already positively confirmed would deadlock the
# instance's bar path indefinitely -- so an exact matching EntryPackageAbsent
# from the corrective cancel must clear both fields immediately, without
# requiring another recovery-state GET.
# ---------------------------------------------------------------------------


def test_exact_matching_absent_confirmation_from_cancel_completes_removal_immediately() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package()),
        cancel_result=EntryPackageAbsent("ema_pullback:abc", "cycle-1"),
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle is None
    assert result.pending_entry_recovery is None
    # Runtime must not require a second recovery-state GET to complete the
    # removal -- the query happened exactly once, inside this same attempt.
    assert len(port.query_calls) == 1


def test_corrective_cancel_public_error_leaves_both_fields_unchanged() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package()),
        cancel_result=EntryPackageInternalError("boom"),
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle == _existing_cycle()
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-1")


@pytest.mark.parametrize(
    "error",
    [
        AbiEntryPackageTimeout("timed out"),
        AbiEntryPackageNetworkFailure("network down"),
        AbiEntryPackageProtocolError("invalid response"),
    ],
)
def test_corrective_cancel_transport_or_protocol_exception_leaves_both_fields_unchanged(
    error: Exception,
) -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package()),
        cancel_error=error,
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle == _existing_cycle()
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-1")


def test_corrective_cancel_unexpected_applied_result_fails_closed() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package()),
        cancel_result=EntryPackageApplied(
            "ema_pullback:abc", "cycle-1", wire_desired_entry(), "0.01"
        ),
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle == _existing_cycle()
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-1")


@pytest.mark.parametrize(
    "mismatched",
    [
        EntryPackageAbsent("other-instance", "cycle-1"),
        EntryPackageAbsent("ema_pullback:abc", "other-cycle"),
    ],
)
def test_corrective_cancel_identity_mismatch_fails_closed(
    mismatched: EntryPackageAbsent,
) -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_result=EntryOrderLiveRecoveryState(applied_entry_package=applied_entry_package()),
        cancel_result=mismatched,
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.current_trade_cycle == _existing_cycle()
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-1")


# ---------------------------------------------------------------------------
# Failed or inconclusive queries: uniform "leave untouched" handling,
# regardless of how many prior attempts already failed the same way (no
# wall-clock gate, no escalation, no distinction between failure reasons).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        AbiEntryCycleRecoveryUnavailable("boom"),
        AbiEntryCycleRecoveryUnknownTradeCycleBinding("no correlation record"),
    ],
)
def test_a_failed_or_inconclusive_query_leaves_the_marker_untouched(error: Exception) -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    port = FakeAbiEntryCycleRecoveryPort(query_error=error)
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-new")
    assert result.current_trade_cycle is None
    assert port.cancel_calls == []


def test_unknown_trade_cycle_binding_is_never_treated_as_terminal_without_fill() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=_existing_cycle(),
        pending_entry_recovery=PendingEntryRecovery("cycle-1"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_error=AbiEntryCycleRecoveryUnknownTradeCycleBinding("no correlation record")
    )
    resolver = _make_resolver(repository, port)

    resolver.attempt(_SID)

    result = repository.get(_SID)
    assert result is not None
    # Neither current_trade_cycle nor pending_entry_recovery changed.
    assert result.current_trade_cycle == _existing_cycle()
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-1")


def test_repeated_failed_attempts_never_escalate_or_give_up() -> None:
    """No attempt-count or elapsed-time threshold changes resolver behavior
    (task 8.9): many consecutive failed attempts still each independently
    query ABI and each independently leave the marker untouched."""
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    port = FakeAbiEntryCycleRecoveryPort(
        query_error=AbiEntryCycleRecoveryUnavailable("boom")
    )
    resolver = _make_resolver(repository, port)

    for _ in range(50):
        resolver.attempt(_SID)

    assert len(port.query_calls) == 50
    result = repository.get(_SID)
    assert result is not None
    assert result.pending_entry_recovery == PendingEntryRecovery("cycle-new")


# ---------------------------------------------------------------------------
# Concurrency: the same keyed mutex bar processing and the first-fill
# webhook path already share.
# ---------------------------------------------------------------------------


def _is_key_locked(registry: StrategyInstanceKeyedMutexRegistry, sid: str) -> bool:
    """White-box probe: a non-blocking acquire attempt on the exact lock the
    production `hold(...)` context manager uses proves whether the critical
    section is genuinely held at the moment a collaborator is invoked."""
    lock = registry._locks.get(sid)  # type: ignore[attr-defined]
    if lock is None:
        return False
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True


def test_attempt_holds_the_shared_keyed_mutex_for_its_full_duration() -> None:
    repository, _ = _repository_with_state(
        current_trade_cycle=None,
        pending_entry_recovery=PendingEntryRecovery("cycle-new"),
    )
    registry = StrategyInstanceKeyedMutexRegistry()
    observed_locked: list[bool] = []

    class _ObservingPort(FakeAbiEntryCycleRecoveryPort):
        def query(self, strategy_instance_id: str, trade_cycle_id: str) -> RecoveryStateResponse:
            observed_locked.append(_is_key_locked(registry, strategy_instance_id))
            return super().query(strategy_instance_id, trade_cycle_id)

    port = _ObservingPort(query_result=TerminalWithoutFillRecoveryState())
    resolver = UncertainExchangeStateResolver(
        state_repository=repository,
        keyed_mutex_registry=registry,
        abi_entry_cycle_recovery=port,  # type: ignore[arg-type]
    )

    assert _is_key_locked(registry, _SID) is False
    resolver.attempt(_SID)

    assert observed_locked == [True]
    assert _is_key_locked(registry, _SID) is False


def applied_package() -> AppliedEntryPackage:
    return AppliedEntryPackage(desired_entry(), "0.01")
