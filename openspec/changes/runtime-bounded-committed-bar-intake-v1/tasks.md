# Tasks: Bounded Committed-Bar Intake v1

## 1. Queue and worker

- [ ] Add `runtime/committed_bar_intake/queue.py` with a thin
      `queue.Queue[CommittedBarEvent]` construction helper taking a fixed
      `maxsize` — no custom class needed beyond what's necessary to type the
      queue and centralize its construction in one place.
- [ ] Add `runtime/committed_bar_intake/worker.py` with
      `CommittedBarIntakeWorker`: constructor takes the queue, the existing
      `CommittedBarOrchestrator` instance, and a logger; exposes `start()`,
      `stop_once()`, and an internal `_run()` thread target.
- [ ] `start()` SHALL spawn exactly one non-daemon `threading.Thread` running
      `_run()` and SHALL be called at most once per `CommittedBarIntakeWorker`
      instance (guard with an internal flag; a second call is a programming
      error, not a silently-ignored no-op — raise).
- [ ] `_run()` SHALL loop: `queue.get(timeout=0.2)` (catching `queue.Empty`
      to re-check the stop condition), then `orchestrator.process(event)`
      wrapped in `try/except Exception` that logs via
      `logger.exception(...)` and never re-raises out of `_run()`, then
      `queue.task_done()` in a `finally`.
- [ ] `stop_once()` SHALL set an internal `threading.Event`, then join the
      worker thread with a bounded timeout, and SHALL be idempotent — a
      second call is a no-op, matching `_OutboundHttpClientLifecycle
      .close_all_once()`'s existing idempotency pattern.

## 2. Configuration

- [ ] Add `committed_bar_queue_capacity: int` to `RuntimeConfig`
      (`config/model.py`), with the same "no meaningful hardcoded default"
      posture as the other required fields it sits alongside — no fallback
      value that would let a missing environment variable pass silently.
- [ ] Extend `RuntimeConfig.__post_init__` to validate
      `committed_bar_queue_capacity >= 1`, raising `ValueError` with a
      message naming `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY`, in the same
      constructor pass as the existing `RUNTIME_PORT` bounds check.
- [ ] Extend `load_runtime_config` (`config/loader.py`) to read
      `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` via a new integer-parsing
      helper mirroring `_require_float`, raising `ValueError` for a missing
      or non-integer value before `RuntimeConfig` is constructed.
- [ ] Set the documented default of `64` only in documentation/deployment
      configuration, not as a silent in-code fallback — the field remains
      required, matching every other outbound-adapter configuration field's
      existing fail-closed posture.

## 3. HTTP endpoint

- [ ] Modify `closed_bar_webhook` (`adapters/http/app.py`) to remove the
      `background_tasks: BackgroundTasks` parameter and the
      `background_tasks.add_task(...)` call.
- [ ] Replace the removed call with
      `app.state.committed_bar_intake_queue.put_nowait(committed_bar)`
      wrapped in a `try/except queue.Full` that returns the existing `503`
      `NotReadyResponse` envelope — do not introduce a new response model.
- [ ] Keep the existing `if not app.state.ready or
      app.state.committed_bar_intake_queue is None` readiness guard shape
      (renaming only the attribute being checked from
      `process_committed_bar` to `committed_bar_intake_queue`), so an
      unready application still returns the existing not-ready response
      before attempting to enqueue anything.
- [ ] Keep `_trace_id = app.state.trace_id_factory()` generated and
      discarded exactly as today — do not thread it into the queue item or
      the worker.
- [ ] Remove the now-unused `BackgroundUseCase` type alias and the
      `process_committed_bar` parameter from `create_http_app(...)`'s
      signature; replace it with a `committed_bar_intake_queue` parameter of
      the appropriate `queue.Queue[CommittedBarEvent] | None` type.

## 4. Composition root

- [ ] Modify `build_application` (`bootstrap/application.py`) to construct
      the queue (via the task-1 helper, sized from
      `config.committed_bar_queue_capacity`) and exactly one
      `CommittedBarIntakeWorker`, wired to the existing, unmodified
      `orchestrator` (`CommittedBarOrchestrator`) instance already
      constructed in this function today — do not construct a second
      `CommittedBarOrchestrator`.
- [ ] Remove the `process_committed_bar` closure and its use as
      `create_http_app(...)`'s `process_committed_bar` argument; pass the
      constructed queue into `create_http_app(...)` instead.
- [ ] Modify the `_lifespan` context manager to call
      `intake_worker.start()` before `yield` and
      `intake_worker.stop_once()` in the `finally` block, ordered before
      (or alongside — order between these two SHALL NOT matter for
      correctness) `lifecycle.close_all_once()`.
- [ ] On any construction failure inside `build_application`'s existing
      try/except rollback path, ensure the intake worker is never left
      running: either it was never started (failure occurred before its
      construction step) or it is stopped as part of the same rollback that
      already closes the four outbound HTTP clients.
- [ ] Expose the constructed queue and worker on `app.state` (mirroring how
      `state_repository`/`keyed_mutex_registry`/`outbound_http_clients` are
      already exposed) for test and operational access.

## 5. Verification — HTTP boundary

- [ ] Test: a valid webhook request returns `200 {"status":"accepted"}`
      without `CommittedBarOrchestrator.process` having been called
      (assert via a fake orchestrator whose `process` records calls and is
      not yet invoked at the point the HTTP response is returned).
- [ ] Test: existing invalid-request validation behavior (missing field,
      wrong type, empty string, negative `open_time_ms`) is unchanged —
      still returns `400 {"status":"rejected","reason":"invalid_webhook"}`.
- [ ] Test: existing not-ready behavior (`app.state.ready is False`) is
      unchanged — still returns `503 {"status":"not_ready"}` and does not
      touch the queue.
- [ ] Test: filling the queue to capacity, then sending one more valid
      webhook request, returns `503 {"status":"not_ready"}` and creates zero
      processing work (assert the fake orchestrator's `process` was not
      called for the rejected event, and the queue's size is unchanged by
      the rejection).

## 6. Verification — worker concurrency and ordering

- [ ] Deterministic (non-sleep-based) test proving at most one
      `CommittedBarOrchestrator.process` call is in flight at any instant:
      use a fake orchestrator whose `process` blocks on a controllable
      gate/event, enqueue two events, assert the second `process` call does
      not start until the first is released.
- [ ] Test: three or more accepted events are processed by the worker in
      the exact order they were enqueued (FIFO), using a fake orchestrator
      that records call order.
- [ ] Test: one event whose processing raises (simulate a
      `CommittedBarPreparationError` from a fake orchestrator) is logged,
      and the worker continues to process the next queued event without the
      worker thread dying.
- [ ] Test: for one accepted event, the existing sequential, ascending-
      `strategy_instance_id`-ordered fan-out behavior of
      `CommittedBarOrchestrator.process` is unchanged — reuse or extend the
      existing orchestrator-level test coverage rather than re-deriving it,
      confirming this change did not alter that method's internal behavior.

## 7. Verification — keyed-mutex interaction

- [ ] Test: the existing keyed-mutex critical section
      (`StrategyRuntimeOrchestrator.process`'s `with self
      ._keyed_mutex_registry.hold(...)`) remains held across the full
      state-load → engine-projection → reconciliation → state-save sequence
      when invoked from the intake worker thread (adapt or reuse the
      existing keyed-coordination test approach against the new call path).
- [ ] Test: a first-fill request for the same `strategy_instance_id` as an
      in-flight committed-bar cycle blocks until the intake worker's
      critical section releases, then observes the freshly saved state —
      extend
      `tests/integration/http/test_first_fill_shared_writer_serialization.py`
      to exercise the new intake-worker call path instead of (or in
      addition to) the removed `BackgroundTasks` path.
- [ ] Test: a first-fill request for a *different* `strategy_instance_id*`
      is not blocked while the intake worker holds another instance's
      critical section (extend the same existing test file).

## 8. Verification — idempotency and duplicates

- [ ] Test: two accepted events with identical
      `instrument`/`timeframe`/`open_time_ms` (and therefore an unchanged
      desired entry) result in the existing `NoOp` reconciliation path on
      the second event — no duplicate trade cycle, no duplicate ABI call —
      proving the queue boundary needed no new dedup logic.

## 9. Verification — lifecycle

- [ ] Test: `build_application` with valid configuration constructs exactly
      one queue and exactly one worker, and the worker's thread is alive
      after construction.
- [ ] Test: application shutdown (exiting the lifespan context) stops the
      worker thread within a bounded time budget, without waiting for the
      queue to drain, even when items remain queued.
- [ ] Test: calling `stop_once()` twice (simulating shutdown running twice,
      or an explicit second call in a test) is a no-op the second time — no
      exception, no double-join error.
- [ ] Test: a construction failure partway through `build_application`
      (simulate a later adapter constructor rejecting its configuration)
      results in a `ready=False` application with no running worker thread
      left behind.

## 10. Configuration verification

- [ ] Test: `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` missing, empty, or
      non-integer raises `ValueError` from `load_runtime_config` before any
      outbound HTTP client or the queue/worker is constructed.
- [ ] Test: `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY=0` or a negative value
      raises `ValueError` from `RuntimeConfig.__post_init__`.
- [ ] Test: a valid positive integer value is reflected exactly as the
      constructed queue's `maxsize`.

## 11. Multi-process guard documentation

- [ ] Add one explicit test or doctest-style assertion (whichever matches
      existing repository convention for documenting accepted limitations)
      that `bootstrap/main.py`'s `uvicorn.run(...)` call is invoked with no
      `workers=` argument, as a canary against silently regressing into a
      multi-worker deployment that would silently break this change's
      single-worker concurrency guarantee. This is a documentation/canary
      test, not a runtime enforcement mechanism — multi-process deployment
      remains explicitly unsupported and undetected at runtime, matching
      the existing, already-documented gap.

## 12. Canonical documentation sync

- [ ] Update `docs/system-plans/` references to the closed-bar webhook's
      `BackgroundTasks`-based dispatch (if any exist) to describe the new
      bounded-queue/single-worker dispatch instead, preserving the existing
      "single-process, single-worker" framing already present in those
      documents.
