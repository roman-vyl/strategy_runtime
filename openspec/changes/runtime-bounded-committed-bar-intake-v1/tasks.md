# Tasks: Bounded Committed-Bar Intake v1

## 1. Intake boundary

- [x] Add `runtime/committed_bar_intake/boundary.py` with
      `CommittedBarIntakeBoundary`: wraps one
      `queue.Queue[CommittedBarEvent](maxsize=capacity)`; exposes
      `put_nowait(event)`, `stop_accepting()`, `get(timeout)`, `task_done()`.
      No caller outside this module holds a reference to the underlying
      `queue.Queue` directly.
- [x] `put_nowait(event)` and `stop_accepting()` SHALL share one
      `threading.Lock` (`_accept_lock`), so the two operations linearize:
      either a given `put_nowait` call acquires the lock before a concurrent
      `stop_accepting()` call (the event reaches the underlying queue,
      subject to the normal capacity check), or `stop_accepting()` acquires
      it first (`put_nowait` raises `IntakeNotAccepting` before ever calling
      the underlying queue's `put_nowait`). There is no third outcome.
- [x] Define `IntakeNotAccepting` as a distinct exception type from
      `queue.Full` — both are raised by `put_nowait`, but for different
      reasons, and callers (the HTTP handler) MUST be able to tell them
      apart for logging purposes (see task 3).
- [x] `get(timeout)` and `task_done()` are worker-only (single consumer);
      they delegate directly to the underlying `queue.Queue`.
- [x] `CommittedBarIntakeBoundary.__init__` SHALL validate its own
      `capacity` argument locally (`type(capacity) is int` and `capacity >
      0`, `ValueError` otherwise, `bool` explicitly rejected) before
      constructing the underlying `queue.Queue` — `queue.Queue(maxsize=0)`
      and negative `maxsize` both silently mean "unbounded" to the standard
      library, so this local invariant is what actually prevents this
      boundary from ever becoming one, independent of and in addition to
      `RuntimeConfig`'s own production-configuration gate.

## 2. Worker with atomic stop/start boundary

- [x] Add `runtime/committed_bar_intake/worker.py` with
      `CommittedBarIntakeWorker`: constructor takes the
      `CommittedBarIntakeBoundary`, the existing `CommittedBarOrchestrator`
      instance, and a logger; exposes `start()`, `stop_once()`, and an
      internal `_run()` thread target.
- [x] Implement a small state machine with exactly four states —
      `NOT_STARTED`, `RUNNING`, `STOPPING`, `STOPPED` — and two locks: a
      short-held `_lifecycle_lock` guarding state reads/writes and the
      current-event handoff (never held across `boundary.get(...)`,
      `orchestrator.process(...)`, or `thread.join()`), and a `_stop_lock`
      that fully serializes the body of `stop_once()` so only one caller
      ever reaches `thread.join()`.
- [x] `start()` SHALL, under `_lifecycle_lock`, require `_state ==
      NOT_STARTED`, transition to `RUNNING`, spawn exactly one non-daemon
      `threading.Thread` running `_run()`, and SHALL be called at most once
      per instance (a second call is a programming error — raise, not a
      silent no-op).
- [x] `_run()` SHALL loop: `boundary.get(timeout=0.2)` (catching
      `queue.Empty` to re-check state, under `_lifecycle_lock`, and exit if
      not `RUNNING`); after a successful dequeue, acquire
      `_lifecycle_lock` **before** calling `orchestrator.process`: if state
      is not `RUNNING` (i.e. `STOPPING` or `STOPPED`), discard the dequeued
      event, call `boundary.task_done()`, and exit `_run()` without
      processing; otherwise record the event as current and release the
      lock **before** calling `orchestrator.process(event)`. This exact
      ordering — dequeue, then acquire lock, then decide, then release lock,
      then process — is what makes the dequeue-vs-stop race deterministic:
      either the event became current before `stop_once()`'s transition (in
      which case shutdown waits for it), or `stop_once()`'s transition won
      first (in which case the event never starts).
- [x] `orchestrator.process(event)` SHALL run with `_lifecycle_lock`
      released — the lock's only job is to make the start/discard decision
      atomic with respect to `stop_once()`, not to serialize processing
      itself.
- [x] One event whose processing raises SHALL be caught (`try/except
      Exception` around `orchestrator.process`, logging via
      `logger.exception(...)`) and SHALL NOT propagate out of `_run()`;
      `boundary.task_done()` SHALL be called in a `finally` regardless of
      outcome.
- [x] `stop_once()` SHALL, under `_stop_lock` (serializing all callers):
    - if `_state == NOT_STARTED`: transition directly to `STOPPED` and
      return, **without** calling `.join()` on a thread that was never
      started;
    - if `_state == STOPPED`: return immediately (no-op);
    - if `_state == RUNNING`: transition to `STOPPING` under
      `_lifecycle_lock`, release the lock, call `self._thread.join()` with
      **no timeout** (not a small, arbitrary bounded one — a bounded join
      could return while the thread is still mid-`process(...)`, letting a
      caller incorrectly treat the worker as stopped), then transition to
      `STOPPED` under `_lifecycle_lock`.
    - A second, concurrent caller blocks on `_stop_lock` until the first
      caller has already driven the state to `STOPPED`; it then observes
      `STOPPED` and returns without itself calling `.join()` — only the
      first caller performs the join.

## 3. HTTP endpoint

- [x] Modify `closed_bar_webhook` (`adapters/http/app.py`) to remove the
      `background_tasks: BackgroundTasks` parameter and the
      `background_tasks.add_task(...)` call.
- [x] Replace the removed call with
      `app.state.committed_bar_intake.put_nowait(committed_bar)`, wrapped
      in **two** distinct `except` clauses:
    - `except IntakeNotAccepting:` — log at `WARNING` with reason
      `intake_stopping` (or `not_accepting`) containing `instrument`,
      `timeframe`, `open_time_ms`, then return the existing `503`
      `NotReadyResponse` envelope;
    - `except queue.Full:` — log at `ERROR` with reason `queue_full`
      containing `instrument`, `timeframe`, `open_time_ms`, and the
      configured `committed_bar_queue_capacity`, then return the same `503`
      `NotReadyResponse` envelope.
      Do not introduce a new response model for either case — both reuse
      the existing envelope; only the server-side log reason differs.
- [x] Keep the existing `if not app.state.ready or
      app.state.committed_bar_intake is None` readiness guard shape
      (renaming only the attribute being checked from
      `process_committed_bar` to `committed_bar_intake`), so an unready
      application still returns the existing not-ready response before
      attempting to enqueue anything.
- [x] Keep `_trace_id = app.state.trace_id_factory()` generated and
      discarded exactly as today — do not thread it into the boundary or
      the worker.
- [x] Remove the now-unused `BackgroundUseCase` type alias and the
      `process_committed_bar` parameter from `create_http_app(...)`'s
      signature; replace it with a `committed_bar_intake` parameter of type
      `CommittedBarIntakeBoundary | None`. Also expose the configured
      `committed_bar_queue_capacity` on `app.state` (or on the boundary
      itself) so the `queue_full` log line can include it without a second
      configuration lookup.

## 4. Composition root

- [x] Modify `build_application` (`bootstrap/application.py`) to construct
      the intake boundary (task 1, sized from
      `config.committed_bar_queue_capacity`) and exactly one
      `CommittedBarIntakeWorker` (task 2), wired to the existing,
      unmodified `orchestrator` (`CommittedBarOrchestrator`) instance
      already constructed in this function today — do not construct a
      second `CommittedBarOrchestrator`.
- [x] Remove the `process_committed_bar` closure and its use as
      `create_http_app(...)`'s `process_committed_bar` argument; pass the
      constructed boundary into `create_http_app(...)` instead.
- [x] Modify the `_lifespan` context manager to the following exact
      sequence in the `finally` block, in this exact order:
      `intake.stop_accepting()` (synchronous, on the event-loop thread —
      it never blocks); then
      `await asyncio.to_thread(intake_worker.stop_once)` (offloaded because
      `stop_once()` can call an untimed `thread.join()` — see task 2 — and
      MUST NOT block the event loop directly); then
      `lifecycle.close_all_once()`. Each step SHALL complete before the
      next begins.
- [x] On any construction failure inside `build_application`'s existing
      try/except rollback path, ensure the intake worker is never left
      running: either it was never started (failure occurred before its
      construction step) or it is stopped via the same three-step sequence
      above, as part of the same rollback path that already closes the
      four outbound HTTP clients.
- [x] Expose the constructed boundary and worker on `app.state` (mirroring
      how `state_repository`/`keyed_mutex_registry`/`outbound_http_clients`
      are already exposed) for test and operational access.
- [x] `intake_worker.start()` SHALL be called *inside* `_lifespan`'s `try`
      block, not before it, so that if `start()` itself raises, the
      `finally` block's full cleanup sequence (`stop_accepting()`,
      offloaded `stop_once()`, `close_all_once()`) still runs before the
      original startup error propagates uncaught — no swallowed error, no
      faked `ready`-shaped outcome, and no orphaned worker thread.
- [x] `CommittedBarIntakeWorker.start()` SHALL publish `RUNNING` and call
      the real `thread.start()` as one atomic step under `_lifecycle_lock`
      (constructing the `Thread` object first, outside the lock, but not
      calling `.start()` on it until the lock is held), so a concurrent
      `stop_once()` can never observe `RUNNING` before the underlying OS
      thread has actually been started — closing the race where
      `stop_once()` could otherwise call `.join()` on a thread that was
      never really started. If `thread.start()` itself raises, the worker
      transitions directly to `STOPPED` (not left `RUNNING`/`STOPPING`)
      before the original exception is re-raised.

## 5. Verification — HTTP boundary

- [x] Test: a valid webhook request returns `200 {"status":"accepted"}`
      without `CommittedBarOrchestrator.process` having been called
      (assert via a fake orchestrator whose `process` records calls and is
      not yet invoked at the point the HTTP response is returned).
- [x] Test: existing invalid-request validation behavior (missing field,
      wrong type, empty string, negative `open_time_ms`) is unchanged —
      still returns `400 {"status":"rejected","reason":"invalid_webhook"}`.
- [x] Test: existing not-ready behavior (`app.state.ready is False`) is
      unchanged — still returns `503 {"status":"not_ready"}` and does not
      touch the boundary.
- [x] Test: filling the boundary to capacity, then sending one more valid
      webhook request, returns `503 {"status":"not_ready"}`, creates zero
      processing work (the fake orchestrator's `process` was not called),
      and emits the `queue_full` log line containing `instrument`,
      `timeframe`, `open_time_ms`, and the configured capacity.
- [x] Test: calling `stop_accepting()` on the boundary directly (without
      exhausting capacity), then sending a valid webhook request, returns
      `503 {"status":"not_ready"}`, does not enqueue the event (queue size
      unchanged), and emits the `intake_stopping` log line containing
      `instrument`, `timeframe`, `open_time_ms` — proving the two rejection
      reasons are logged distinguishably even though the wire response is
      identical.
- [x] Test (linearization): with a fake boundary or by driving the real
      `_accept_lock` deterministically, confirm there is no observable
      outcome where a `put_nowait` call that started before a concurrent
      `stop_accepting()` call is rejected, nor one where a `put_nowait`
      call that started after `stop_accepting()` completed is accepted.

## 6. Verification — worker concurrency, ordering, and the atomic race

- [x] Deterministic (non-sleep-based) test proving at most one
      `CommittedBarOrchestrator.process` call is in flight at any instant:
      use a fake orchestrator whose `process` blocks on a controllable
      gate/event, enqueue two events, assert the second `process` call does
      not start until the first is released.
- [x] Test: three or more accepted events are processed by the worker in
      the exact order they were enqueued (FIFO), using a fake orchestrator
      that records call order.
- [x] Test: one event whose processing raises (simulate a
      `CommittedBarPreparationError` from a fake orchestrator) is logged,
      and the worker continues to process the next queued event without the
      worker thread dying.
- [x] Test: for one accepted event, the existing sequential, ascending-
      `strategy_instance_id`-ordered fan-out behavior of
      `CommittedBarOrchestrator.process` is unchanged — reuse or extend the
      existing orchestrator-level test coverage rather than re-deriving it,
      confirming this change did not alter that method's internal behavior.
- [x] Deterministic test (dequeue-vs-stop race, event wins): using a fake
      orchestrator whose `process` blocks on a controllable gate, arrange
      for `_run()` to have already acquired `_lifecycle_lock` and marked an
      event as current (a test seam or a synchronization point exposed for
      this purpose) before `stop_once()` is invoked from another thread;
      assert `stop_once()` blocks until the gate is released and the
      current event's `process(...)` call is allowed to run to completion.
- [x] Deterministic test (dequeue-vs-stop race, stop wins): arrange for
      `stop_once()` to acquire `_lifecycle_lock` and transition to
      `STOPPING` before a concurrently dequeued event reaches its own
      `_lifecycle_lock` acquisition; assert that event is discarded
      (`orchestrator.process` is never called for it) and `_run()` exits.
- [x] Test: `_lifecycle_lock` is never held while `orchestrator.process(...)`
      is executing — e.g. by asserting a different thread can acquire
      `_lifecycle_lock` (or complete an operation that requires it, such as
      a concurrent `stop_once()` reaching its own lock acquisition and
      observing the current-event marker) while a fake orchestrator's
      `process` is deliberately blocked mid-call.

## 7. Verification — keyed-mutex interaction

- [x] Test: the existing keyed-mutex critical section
      (`StrategyRuntimeOrchestrator.process`'s `with self
      ._keyed_mutex_registry.hold(...)`) remains held across the full
      state-load → engine-projection → reconciliation → state-save sequence
      when invoked from the intake worker thread. Proven by
      `test_first_fill_waits_for_the_real_strategy_runtime_orchestrator_critical_section`
      in
      `tests/integration/http/test_first_fill_shared_writer_serialization.py`,
      which drives the real, unmodified `StrategyRuntimeOrchestrator` (and
      `EntryReconciliationOrchestrator`) through the real intake worker
      thread, with fakes only at `StrategyRuntimeOrchestrator`'s own
      established collaborator ports (open-position resolution, Engine
      use-case routing, reconciliation execution) — not a direct
      mutex-holding stand-in dispatcher. (The earlier, simpler
      `_GatedMutexHoldingDispatcher`-based tests in the same file remain, but
      only prove the intake worker's dispatch call path reaches the shared
      registry — they are not what proves this specific requirement.)
- [x] Test: a first-fill request for the same `strategy_instance_id` as an
      in-flight committed-bar cycle blocks until the intake worker's real
      critical section releases, then observes the freshly saved state —
      same test as above: first-fill is proven blocked (zero
      `repository.get(...)` calls while the real cycle's Engine-projection
      step is gated) and, once unblocked, freezes exactly the trade cycle
      the real cycle applied and saved. "Blocked" is proven by a definitive
      per-key mutex-attempt signal (`_MutexAttemptSpy.attempt_event`, set
      the instant first-fill's own call reaches `hold(...)`, distinguished
      from the real cycle's own earlier attempt on the same key by
      clearing the event first) plus a bounded re-checked poll that
      `repository.get(...)` stays empty — not a single arbitrary
      `time.sleep` assumed to be long enough for first-fill to have
      reached the mutex.
- [x] Test: a first-fill request for a *different* `strategy_instance_id`
      is not blocked while the intake worker holds another instance's real
      critical section —
      `test_different_instance_first_fill_completes_while_the_real_cycle_remains_blocked`,
      same file. Also asserts the call completes in well under 2 seconds:
      empirically verified (by temporarily forcing
      `StrategyInstanceKeyedMutexRegistry` to hand out one shared lock for
      every key) that without this bound, an accidentally-global mutex
      would still make this test pass — just ~5s slower, via the fake
      Engine-projection gate's own internal `wait(timeout=5)` fallback
      unwinding instance-A's critical section by exception and releasing
      the (bugged, shared) lock. The same elapsed-time bound and
      definitive mutex-attempt signal are applied to the earlier
      `_make_harness`- and `_GatedMutexHoldingDispatcher`-based same/
      different-instance tests in the same file, for consistency.

## 8. Verification — idempotency and duplicates

- [x] Test: two accepted events with identical
      `instrument`/`timeframe`/`open_time_ms` (and therefore an unchanged
      desired entry) result in the existing `NoOp` reconciliation path on
      the second event: no second trade cycle is created, and no duplicate
      ABI entry-package create/amend/cancel or duplicate exchange mutation
      results from the identical event. Do not assert "zero duplicate ABI
      calls" — the second event may still perform an existing ABI
      open-position lookup/read as part of normal processing; only the
      *mutating* outcomes (trade cycle creation, entry-package
      create/amend/cancel, exchange order mutation) are asserted absent on
      the duplicate. This proves the boundary needed no new dedup logic,
      without over-claiming what "no duplicate" means.

## 9. Verification — lifecycle

- [x] Test: `build_application` with valid configuration constructs exactly
      one intake boundary and exactly one worker object; immediately after
      `build_application` returns (before the FastAPI lifespan has started),
      the worker object exists but its thread is **not** alive and its
      state is `NOT_STARTED`.
- [x] Test: after the FastAPI lifespan has started (e.g. via a test client's
      startup), the worker's thread is alive, exactly once, and its state
      is `RUNNING`.
- [x] Test: after the FastAPI lifespan has shut down (e.g. via a test
      client's shutdown), the worker's thread is no longer alive and its
      state is `STOPPED`.
- [x] Test (shutdown, pending discard): with one or more events sitting in
      the boundary and none currently being processed, triggering shutdown
      results in those queued events never being passed to
      `orchestrator.process(...)` — assert via a fake orchestrator whose
      `process` records calls and shows zero calls for the discarded items.
- [x] Test (shutdown, in-flight completion): with a fake orchestrator whose
      `process(...)` blocks on a controllable gate, start processing one
      event, then trigger shutdown (`stop_accepting()` then `stop_once()`)
      while that call is still blocked on the gate; assert `stop_once()`
      has not returned yet; release the gate; assert `stop_once()` then
      returns and the blocked `process(...)` call was allowed to run to
      completion rather than being abandoned.
- [x] Test (shutdown, client-close ordering): using the same
      blocked-`process(...)` setup, assert that none of the four outbound
      HTTP clients are closed while the gate is still held (i.e. while the
      worker thread is still mid-`process(...)`); release the gate; assert
      the clients are closed only after `stop_once()` returns.
- [x] Test (shutdown, stop-accepting-first): trigger shutdown while one
      event is blocked mid-`process(...)`; while still blocked, send a new
      webhook request and assert it is rejected with `intake_stopping`
      (not enqueued) — proving `stop_accepting()` takes effect immediately,
      independent of how long the in-flight event takes to finish.
- [x] Test (event loop not blocked during join): with a fake orchestrator's
      `process` blocked on a controllable gate and lifespan shutdown
      triggered (so `stop_once()` is executing its `thread.join()` inside
      the `asyncio.to_thread` offload), start an independent, trivial
      `asyncio` probe task (e.g. one that increments a counter after
      `await asyncio.sleep(0)` in a loop) on the same event loop; assert the
      probe task continues to make progress while the join is still
      waiting in its offloaded thread; assert the four outbound HTTP
      clients remain open during this window; release the gate; assert the
      worker exits, the clients are closed exactly once, and the lifespan
      shutdown coroutine completes.
- [x] Test (no orphan thread): after shutdown completes, assert the
      worker's thread object reports not alive, and no equivalent orphaned
      non-daemon thread remains referencing the shut-down application's
      boundary or orchestrator.
- [x] Test: calling `stop_once()` twice (simulating shutdown running twice,
      or an explicit second call in a test) is a no-op the second time — no
      exception, no second `.join()` call, and the four outbound HTTP
      clients are closed exactly once total, not once per `stop_once()`
      call.
- [x] Test (concurrent stop_once callers): invoke `stop_once()` from two
      threads at approximately the same time while one event is blocked
      mid-`process(...)`; assert only one of the two callers' code path
      actually reaches `thread.join()` (e.g. via a call-count assertion on
      an instrumented join, or by asserting the second caller returns
      promptly once the first caller has completed rather than performing
      its own wait); assert both callers observe `STOPPED` on return.
- [x] Test: a construction failure partway through `build_application`
      (simulate a later adapter constructor rejecting its configuration)
      results in a `ready=False` application with no running worker thread
      left behind.

## 10. Configuration verification

- [x] Test: `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` missing, empty, or
      non-integer raises `ValueError` from `load_runtime_config` before any
      outbound HTTP client or the boundary/worker is constructed.
- [x] Test: `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY=0` or a negative value
      raises `ValueError` from `RuntimeConfig.__post_init__`.
- [x] Test: a valid positive integer value is reflected exactly as the
      constructed boundary's underlying queue `maxsize`.
- [x] `config/runtime.env.example` (the canonical deployment example
      design.md's "Configuration" section refers to) includes
      `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY=256`. Test: reading the real
      file, parsing its `KEY=VALUE` entries, and passing them to
      `load_runtime_config` produces a valid configuration with
      `committed_bar_queue_capacity == 256` — so a future required
      variable missing from that file fails this test instead of only
      being discovered at deployment time.

## 11. Multi-process guard documentation

- [x] Add one explicit test or doctest-style assertion (whichever matches
      existing repository convention for documenting accepted limitations)
      that `bootstrap/main.py`'s `uvicorn.run(...)` call is invoked with no
      `workers=` argument, as a canary against silently regressing into a
      multi-worker deployment that would silently break this change's
      single-worker concurrency guarantee. This is a documentation/canary
      test, not a runtime enforcement mechanism — multi-process deployment
      remains explicitly unsupported and undetected at runtime, matching
      the existing, already-documented gap.

## 12. Canonical documentation sync

- [x] Update `docs/system-plans/` references to the closed-bar webhook's
      `BackgroundTasks`-based dispatch (if any exist) to describe the new
      bounded-boundary/single-worker dispatch instead, preserving the
      existing "single-process, single-worker" framing already present in
      those documents.
- [x] Document explicitly, wherever this change's shutdown behavior is
      described, that the worker layer introduces no forced-interruption
      or hard shutdown timeout: clean shutdown waits for the current event
      to finish, bounded on its network operations by existing finite
      outbound timeouts, but not bounded at all for local work (catalog
      access, mutex waits, repository operations, or a defect) — an
      accepted Live V1 tradeoff, not a proven hang-proof guarantee.
