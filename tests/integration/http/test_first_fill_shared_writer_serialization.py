"""Shared-writer serialization test: one real StrategyInstanceKeyedMutexRegistry
and one real repository, proving the first-fill HTTP path and a closed-bar
writer serialize per strategy_instance_id through the shared mutex, and that
two different instance keys never block each other. No real ABI or Strategy
Engine server is started.

Two tiers, deliberately not three: a minimal tier that isolates the
mutex/first-fill-orchestrator interaction with no intake-queue machinery at
all (cheapest, most isolated surface), and the strongest tier that drives
the real production intake pipeline -- HTTP webhook -> CommittedBarIntake
Boundary -> CommittedBarIntakeWorker -> CommittedBarOrchestrator ->
StrategyRuntimeOrchestrator's real state-load -> projection -> reconcile ->
save critical section. A middle tier that only held the mutex via a fake
dispatcher (proving intake-worker plumbing reaches the shared registry, but
none of StrategyRuntimeOrchestrator's real critical section) was removed:
everything it proved is a strict subset of what the strongest tier already
proves, since the strongest tier necessarily also exercises that same
intake-worker plumbing to reach the real orchestrator."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from strategy_runtime.adapters.http.app import create_http_app
from strategy_runtime.runtime.abi_execution_event.orchestrator import (
    AbiExecutionEventOrchestrator,
)
from strategy_runtime.runtime.committed_bar_intake import (
    CommittedBarIntakeBoundary,
    CommittedBarIntakeWorker,
)
from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation import (
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.orchestrator.orchestrator import StrategyRuntimeOrchestrator
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.state.models import (
    AppliedEntryPackage,
    CurrentTradeCycle,
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import (
    InMemoryStrategyInstanceRuntimeStateRepository,
)
from strategy_runtime.utility.committed_bar import (
    CommittedBarEvent,
    CommittedBarOrchestrator,
    SelectedDeployment,
)
from strategy_runtime.utility.deployment_catalog import DeploymentSpecification
from strategy_runtime.utility.handoff import StrategyCycleHandoffBoundary

_SID_A = "instance-a"
_SID_B = "instance-b"
_TRADE_CYCLE_ID = "cycle-1"
_SOURCE_PLAN_BAR_OPEN_TIME_MS = 900_000
_FIRST_FILL_AT_MS = 905_000


def _desired_entry() -> DesiredEntry:
    return DesiredEntry("long", _SOURCE_PLAN_BAR_OPEN_TIME_MS, "100", "99", "103", "runner")


class _RecordingRepository:
    """Wraps a real InMemoryStrategyInstanceRuntimeStateRepository, recording
    every get(...) call by strategy_instance_id."""

    def __init__(self, inner: InMemoryStrategyInstanceRuntimeStateRepository) -> None:
        self._inner = inner
        self.get_calls: list[str] = []
        self._get_calls_lock = threading.Lock()

    def get_or_create(self, request: object) -> StrategyInstanceRuntimeState:
        return self._inner.get_or_create(request)  # type: ignore[arg-type]

    def get(self, strategy_instance_id: str) -> StrategyInstanceRuntimeState | None:
        with self._get_calls_lock:
            self.get_calls.append(strategy_instance_id)
        return self._inner.get(strategy_instance_id)

    def save(self, state: StrategyInstanceRuntimeState) -> StrategyInstanceRuntimeState:
        return self._inner.save(state)


def _seed(repo: InMemoryStrategyInstanceRuntimeStateRepository, sid: str) -> None:
    request = GetOrCreateStrategyInstanceRuntimeStateRequest(
        strategy_instance_id=sid,
        strategy_id="strategy-x",
        instrument="BTCUSDT.P",
        base_timeframe="15m",
        raw_spec={},
        source_path="a.json",
    )
    base_state = repo.get_or_create(request)
    with_cycle = replace(
        base_state,
        current_trade_cycle=CurrentTradeCycle(
            _TRADE_CYCLE_ID, AppliedEntryPackage(_desired_entry(), "0.01")
        ),
    )
    repo.save(with_cycle)


def _url(sid: str) -> str:
    return f"/v1/strategy-instances/{sid}/trade-cycles/{_TRADE_CYCLE_ID}/first-fill"


def _wait_until(predicate: object, *, timeout: float, interval: float = 0.01) -> bool:
    """Bounded, actively-re-checked wait for a predicate to become true.

    Not a proof-by-sleep: the loop only returns True once the predicate is
    observed true, and returns False if it never becomes true within
    `timeout` -- used to prove something has *not* happened within a
    generous window, rather than assuming a fixed sleep was long enough.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(interval)
    return bool(predicate())  # type: ignore[operator]


class _MutexAttemptSpy:
    """Wrap a real `StrategyInstanceKeyedMutexRegistry`, exposing one
    `threading.Event` per `strategy_instance_id` that fires the instant a
    caller *starts* attempting `hold(strategy_instance_id)` -- before it is
    known whether that attempt blocks on an already-held lock or acquires
    it immediately. Delegates every acquisition to the real registry
    unchanged; this only adds an observable "an attempt started" signal so
    a test can wait for a concurrent caller to have genuinely reached the
    mutex, instead of assuming an arbitrary sleep gave it enough time to.
    """

    def __init__(self, inner: StrategyInstanceKeyedMutexRegistry) -> None:
        self._inner = inner
        self._events: dict[str, threading.Event] = {}
        self._events_lock = threading.Lock()

    def attempt_event(self, strategy_instance_id: str) -> threading.Event:
        with self._events_lock:
            return self._events.setdefault(strategy_instance_id, threading.Event())

    @contextmanager
    def hold(self, strategy_instance_id: str) -> Iterator[None]:
        self.attempt_event(strategy_instance_id).set()
        with self._inner.hold(strategy_instance_id):
            yield


def _assert_first_fill_blocks_then_unblocks(
    client: TestClient,
    registry: _MutexAttemptSpy,
    repo: _RecordingRepository,
    sid: str,
    release_holder: threading.Event,
) -> object:
    """Start a first-fill PUT for `sid` on a background thread, prove it
    reaches -- and stays blocked on -- the real per-key mutex a caller
    already holds, then release that holder and return the PUT's response.

    "Reaches" is a definitive per-key attempt signal (fired the instant
    `hold(sid)` is called, cleared first since the current holder already
    fired it once), not an arbitrary sleep assumed to be long enough for
    first-fill to get there. "Stays blocked" is a bounded, re-checked poll
    that `repository.get(...)` -- the very next statement once the mutex is
    acquired -- stays empty, not a single arbitrary sleep.
    """
    attempt = registry.attempt_event(sid)
    attempt.clear()

    result: dict[str, object] = {}

    def do_put() -> None:
        result["response"] = client.put(_url(sid), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})

    put_thread = threading.Thread(target=do_put)
    put_thread.start()

    assert attempt.wait(timeout=2), "first-fill never attempted the mutex"
    assert not _wait_until(lambda: repo.get_calls != [], timeout=0.5)

    release_holder.set()
    put_thread.join(timeout=5)
    return result["response"]


def _assert_different_instance_first_fill_is_not_blocked(client: TestClient, sid: str) -> object:
    """PUT first-fill for `sid` and assert it completes quickly.

    A genuinely per-instance mutex lets this complete almost instantly. If
    the keyed mutex were accidentally global, this call would instead block
    until whatever gate the concurrently-held *other* instance's critical
    section is waiting on times out on its own and releases that (bugged,
    shared) lock -- so a bound comfortably under that fallback's timeout is
    what actually distinguishes "never blocked" from "eventually released
    by a timeout fallback," which the status code alone cannot.
    """
    started_at = time.monotonic()
    response = client.put(_url(sid), json={"first_fill_at_ms": _FIRST_FILL_AT_MS})
    elapsed = time.monotonic() - started_at
    assert elapsed < 2.0, (
        f"{sid} first-fill took {elapsed:.2f}s -- looks like it was blocked on another "
        "instance's mutex and only unblocked via a timeout fallback"
    )
    return response


# ---------------------------------------------------------------------------
# Minimal tier: mutex + first-fill orchestrator interaction only, no intake
# queue, no worker, no CommittedBarOrchestrator involved at all.
# ---------------------------------------------------------------------------


def _make_harness() -> tuple[TestClient, _RecordingRepository, _MutexAttemptSpy]:
    inner_repo = InMemoryStrategyInstanceRuntimeStateRepository()
    _seed(inner_repo, _SID_A)
    _seed(inner_repo, _SID_B)
    repo = _RecordingRepository(inner_repo)
    registry = _MutexAttemptSpy(StrategyInstanceKeyedMutexRegistry())
    orchestrator = AbiExecutionEventOrchestrator(
        state_repository=repo,  # type: ignore[arg-type]
        keyed_mutex_registry=registry,  # type: ignore[arg-type]
    )
    app = create_http_app(
        ready=True,
        committed_bar_intake=None,
        process_first_fill=orchestrator.process,
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, repo, registry


def test_first_fill_path_waits_for_a_held_closed_bar_writer_then_loads_fresh_state() -> None:
    client, repo, registry = _make_harness()

    writer_holds = threading.Event()
    release_writer = threading.Event()

    def closed_bar_writer() -> None:
        with registry.hold(_SID_A):
            # Simulate closed-bar-writer work under the lock: mutate a
            # harmless field before the first-fill path is ever allowed in.
            current = repo.get(_SID_A)
            assert current is not None
            repo.save(replace(current, risk_multiplier="2"))
            writer_holds.set()
            release_writer.wait(timeout=5)

    writer_thread = threading.Thread(target=closed_bar_writer)
    writer_thread.start()
    assert writer_holds.wait(timeout=2), "closed-bar writer never acquired the mutex"
    repo.get_calls.clear()  # drop the writer's own get(...) call from the count below

    response = _assert_first_fill_blocks_then_unblocks(
        client, registry, repo, _SID_A, release_writer
    )
    writer_thread.join(timeout=5)

    assert response.status_code == 200  # type: ignore[union-attr]
    assert repo.get_calls == [_SID_A]

    # Fresh-state visibility: the writer's pre-release mutation is what the
    # first-fill path saw and persisted forward.
    stored = repo.get(_SID_A)
    assert stored is not None
    assert stored.risk_multiplier == "2"


def test_instance_b_first_fill_is_not_blocked_while_instance_a_mutex_is_held() -> None:
    client, repo, registry = _make_harness()

    writer_holds = threading.Event()
    release_writer = threading.Event()

    def closed_bar_writer() -> None:
        with registry.hold(_SID_A):
            writer_holds.set()
            release_writer.wait(timeout=5)

    writer_thread = threading.Thread(target=closed_bar_writer)
    writer_thread.start()
    assert writer_holds.wait(timeout=2), "closed-bar writer never acquired the mutex"

    try:
        response = _assert_different_instance_first_fill_is_not_blocked(client, _SID_B)
    finally:
        release_writer.set()
        writer_thread.join(timeout=5)

    assert response.status_code == 200  # type: ignore[union-attr]
    assert repo.get_calls == [_SID_B]


# ---------------------------------------------------------------------------
# Strongest tier: the closed-bar side runs the real semantic critical
# section -- state load -> Engine/open-position projection -> reconciliation
# -> state save -- via the real, unmodified StrategyRuntimeOrchestrator and
# EntryReconciliationOrchestrator, invoked from the real
# CommittedBarIntakeWorker thread through the real CommittedBarOrchestrator.
# Only StrategyRuntimeOrchestrator's own established collaborator ports
# (open-position resolution, Engine use-case routing, reconciliation
# execution) are fakes; the keyed-mutex registry, the shared repository, and
# every orchestration class in between are real and shared with first-fill's
# real AbiExecutionEventOrchestrator.
# ---------------------------------------------------------------------------


class _SingleDeploymentCatalog:
    def load_snapshot(self) -> None:
        return None


class _NoOpJournal:
    def orchestration_started(self, **_kwargs: object) -> None: ...
    def orchestration_failed(self, **_kwargs: object) -> None: ...
    def strategy_cycle_outcome(self, **_kwargs: object) -> None: ...
    def orchestration_completed(self, **_kwargs: object) -> None: ...


class _FakeOpenPositionResolver:
    """Stand-in for the real ABI-backed open-position resolver, at its own
    established `OpenPositionResolverPort`."""

    def resolve(
        self, state: StrategyInstanceRuntimeState
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        return PositionResolvedStrategyInstanceRuntimeState(
            runtime_state=state,
            position_open=False,
            first_fill_at_ms=None,
            average_entry_price=None,
        )


class _GatedUseCaseRouter:
    """Stand-in for the real Strategy Engine HTTP call, at its own
    established `StrategyUseCaseRouterPort` -- called from *inside*
    StrategyRuntimeOrchestrator.process's real keyed-mutex critical section,
    after the real get_or_create/resolve steps have already run and before
    the real reconcile/save steps run."""

    def __init__(self, desired_entry: DesiredEntry) -> None:
        self._desired_entry = desired_entry
        self.call_started = threading.Event()
        self.release = threading.Event()

    def route(self, item: PositionResolvedStrategyInstance) -> LiveEntryProjectedStrategyInstance:
        self.call_started.set()
        assert self.release.wait(timeout=5), "release was never set"
        return LiveEntryProjectedStrategyInstance(source=item, desired_entry=self._desired_entry)


class _FakeEntryReconciliationExecutionPort:
    """Stand-in for the real ABI entry-package execution bridge, at its own
    established `EntryReconciliationExecutionPort`."""

    def execute(
        self,
        command: EntryReconciliationCommand,
        source_state: StrategyInstanceRuntimeState,
    ) -> EntryAppliedConfirmation:
        assert command.desired_entry is not None
        return EntryAppliedConfirmation(
            strategy_instance_id=command.strategy_instance_id,
            trade_cycle_id=command.trade_cycle_id,
            applied_desired_entry=command.desired_entry,
            calculated_quantity="1",
        )


def _deployment(sid: str) -> DeploymentSpecification:
    return DeploymentSpecification(
        strategy_instance_id=sid,
        enabled=True,
        instrument="BTCUSDT.P",
        base_timeframe="15m",
        strategy_id="strategy-x",
        raw_spec={},
        source_path="a.json",
    )


class _FixedTargetSelectorWithDeployment:
    def __init__(self, strategy_instance_id: str, deployment: DeploymentSpecification) -> None:
        self._strategy_instance_id = strategy_instance_id
        self._deployment = deployment

    def select(
        self, *, event: CommittedBarEvent, snapshot: object
    ) -> tuple[SelectedDeployment[DeploymentSpecification], ...]:
        return (SelectedDeployment(self._strategy_instance_id, self._deployment),)


def _make_real_semantic_harness(
    target_sid: str,
) -> tuple[
    TestClient,
    _RecordingRepository,
    CommittedBarIntakeWorker,
    _GatedUseCaseRouter,
    _MutexAttemptSpy,
]:
    inner_repo = InMemoryStrategyInstanceRuntimeStateRepository()
    repo = _RecordingRepository(inner_repo)
    registry = _MutexAttemptSpy(StrategyInstanceKeyedMutexRegistry())

    first_fill_orchestrator = AbiExecutionEventOrchestrator(
        state_repository=repo,  # type: ignore[arg-type]
        keyed_mutex_registry=registry,  # type: ignore[arg-type]
    )

    gated_router = _GatedUseCaseRouter(_desired_entry())
    entry_reconciliation_orchestrator = EntryReconciliationOrchestrator(
        lambda: _TRADE_CYCLE_ID,
        _FakeEntryReconciliationExecutionPort(),
    )
    strategy_runtime_orchestrator = StrategyRuntimeOrchestrator(
        state_repository=repo,  # type: ignore[arg-type]
        open_position_resolver=_FakeOpenPositionResolver(),
        use_case_router=gated_router,
        keyed_mutex_registry=registry,  # type: ignore[arg-type]
        entry_reconciliation_orchestrator=entry_reconciliation_orchestrator,
        position_management_orchestrator=MagicMock(),
    )

    def process_strategy_cycle(
        unit: object,
    ) -> None:
        strategy_runtime_orchestrator.process(unit)  # type: ignore[arg-type]

    handoff_boundary = StrategyCycleHandoffBoundary(process_strategy_cycle)
    committed_bar_orchestrator = CommittedBarOrchestrator(
        deployment_catalog=_SingleDeploymentCatalog(),
        deployment_selector=_FixedTargetSelectorWithDeployment(target_sid, _deployment(target_sid)),
        strategy_cycle_dispatcher=handoff_boundary,
        processing_journal=_NoOpJournal(),
    )

    intake = CommittedBarIntakeBoundary(capacity=8)
    worker = CommittedBarIntakeWorker(
        intake,
        committed_bar_orchestrator,
        logging.getLogger("test.shared_writer.real_semantic"),
    )
    worker.start()

    app = create_http_app(
        ready=True,
        committed_bar_intake=intake,
        process_first_fill=first_fill_orchestrator.process,
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, repo, worker, gated_router, registry


def _post_closed_bar(client: TestClient) -> object:
    """The harness's fixed selector always targets its configured
    `target_sid` regardless of this request body's contents."""
    return client.post(
        "/v1/webhooks/closed-bar",
        json={"instrument": "BTCUSDT.P", "timeframe": "15m", "open_time_ms": 1},
    )


def test_first_fill_waits_for_the_real_strategy_runtime_orchestrator_critical_section() -> None:
    client, repo, worker, gated_router, registry = _make_real_semantic_harness(_SID_A)
    try:
        response = _post_closed_bar(client)
        assert response.status_code == 200  # type: ignore[union-attr]
        assert gated_router.call_started.wait(timeout=2), (
            "the real cycle never reached the gated Engine-projection call"
        )

        # StrategyRuntimeOrchestrator's real critical section is open: state
        # has already been loaded and resolved, the Engine-projection call
        # is blocked mid-call, and reconciliation/save are still pending --
        # all under the one real keyed mutex.
        put_response = _assert_first_fill_blocks_then_unblocks(
            client, registry, repo, _SID_A, gated_router.release
        )
    finally:
        gated_router.release.set()
        worker.stop_once()

    assert put_response.status_code == 200  # type: ignore[union-attr]
    assert repo.get_calls == [_SID_A]

    # first-fill only proceeded once the real cycle's reconcile+save had
    # both completed, and it froze exactly what that real cycle saved.
    stored = repo.get(_SID_A)
    assert stored is not None
    assert stored.current_trade_cycle is not None
    assert stored.current_trade_cycle.trade_cycle_id == _TRADE_CYCLE_ID
    applied_entry = stored.current_trade_cycle.applied_entry_package.applied_desired_entry
    assert applied_entry == _desired_entry()
    frozen_context = stored.current_trade_cycle.frozen_entry_context
    assert frozen_context is not None
    assert frozen_context.first_fill_at_ms == _FIRST_FILL_AT_MS


def test_different_instance_first_fill_completes_while_the_real_cycle_remains_blocked() -> None:
    client, repo, worker, gated_router, _registry = _make_real_semantic_harness(_SID_A)
    _seed(repo, _SID_B)  # pre-existing, unrelated trade cycle for a different instance
    try:
        response = _post_closed_bar(client)
        assert response.status_code == 200  # type: ignore[union-attr]
        assert gated_router.call_started.wait(timeout=2), (
            "the real cycle never reached the gated Engine-projection call"
        )

        put_response = _assert_different_instance_first_fill_is_not_blocked(client, _SID_B)
    finally:
        gated_router.release.set()
        worker.stop_once()

    assert put_response.status_code == 200  # type: ignore[union-attr]
    assert repo.get_calls == [_SID_B]
