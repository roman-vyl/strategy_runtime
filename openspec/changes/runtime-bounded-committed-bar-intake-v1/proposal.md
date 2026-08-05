# Proposal: Bounded Committed-Bar Intake v1

## Why

`POST /v1/webhooks/closed-bar` (`adapters/http/app.py:82`) currently
validates a `ClosedBarRequest`, builds a `CommittedBarEvent`, and calls
`background_tasks.add_task(app.state.process_committed_bar, committed_bar)`
before returning `{"status": "accepted"}`. Every accepted webhook request
becomes its own independent `BackgroundTasks` unit, dispatched to Starlette's
thread pool with no bound on how many can run at once.

Market boundary timestamps — the top of an hour, four hours, or midnight
UTC — are exactly when many independently configured MDS streams commit a
candle close within the same wall-clock second. Each commit produces its own
webhook request, each accepted request spawns its own `BackgroundTasks` unit,
and each unit independently calls `CommittedBarOrchestrator.process(...)`,
which independently loads a deployment-catalog snapshot, independently
selects deployments, and for every selected strategy instance independently
calls into the Strategy Engine and ABI over HTTP. A burst of near
-simultaneous webhooks therefore becomes a burst of near-simultaneous,
unbounded concurrent `CommittedBarOrchestrator.process` calls — each one
driving its own concurrent fan-out of Engine and ABI HTTP calls.

### Why the existing keyed mutex does not solve this

`StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)`
(`runtime/coordination/keyed_mutex.py`) already prevents two concurrent
writers from corrupting the *same* strategy instance's state — that
correctness property is unaffected by this change and remains mandatory.
But the mutex is scoped per `strategy_instance_id`; it does nothing to bound
the *number of distinct instances* whose critical sections are open at once,
and it does nothing to bound how many `CommittedBarOrchestrator.process`
calls are simultaneously mid-flight (each doing catalog load, deployment
selection, and multi-instance fan-out *before* any per-instance mutex is
even acquired). A burst of ten simultaneous webhooks for ten different
strategy instances sails straight through the keyed mutex — every instance
gets its own uncontended lock — while still producing ten concurrent
`CommittedBarOrchestrator.process` calls, ten concurrent catalog loads, and
an unbounded number of concurrent outbound Engine/ABI HTTP calls. The mutex
is a per-key correctness guarantee, not a process-wide concurrency bound;
this change adds the missing bound without touching the mutex.

### Why best-effort, not durable delivery

Runtime's own state repository
(`InMemoryStrategyInstanceRuntimeStateRepository`) is already non-durable in
Live V1 — an in-flight committed-bar cycle is already an accepted loss on
process termination (documented in `runtime-production-composition`'s
"Non-durable Live V1 limitation is accepted, not open"). Adding a durable,
replayable intake queue in front of an already-non-durable state layer would
not produce end-to-end durability; it would only add persistence machinery
whose guarantee stops at the queue boundary. Given that, this change accepts
the same class of loss the production composition already accepts: an
accepted-but-unprocessed event is lost if the process terminates before the
worker drains it, and an event is rejected outright (never silently dropped
— the caller receives a fail-closed HTTP response) if the bounded queue is
already full.

### Why this is split across two repositories

MDS decides *whether and when* to notify Runtime and owns the outbound HTTP
attempt (proposed separately as `mds-runtime-committed-bar-webhook-v1`).
Runtime owns everything on its side of that HTTP boundary: accepting the
request, bounding how much of it is buffered, and controlling how many
committed-bar cycles run concurrently. Runtime has no visibility into MDS's
ingestion classification, canonical storage, or realtime supervision, and
this change makes no assumption about MDS's internal queue depth or delivery
semantics beyond the fixed wire contract both proposals share. Each side can
be implemented, tested, and rolled back independently.

## What Changes

- **MODIFIED** `http-closed-bar`: `POST /v1/webhooks/closed-bar` stops using
  `fastapi.BackgroundTasks.add_task(...)` and instead performs one bounded,
  non-blocking enqueue onto a new intake queue. Acceptance semantics
  (`200 {"status":"accepted"}` means "accepted into a volatile queue," not
  "processed") are preserved; the trace-id-generated-then-discarded behavior
  is preserved unchanged; validation and not-ready semantics are preserved
  unchanged. **BREAKING** for the specific case of a full queue: this
  previously-unbounded endpoint now has a bounded intake capacity and can
  return `503` for a reason other than "not ready."
- **ADDED** `committed-bar-intake-queue`: a new capability defining the
  bounded FIFO queue, its exactly-one consumer worker, queue-full behavior,
  and per-event failure isolation.
- **MODIFIED** `runtime-production-composition`: the composition root
  constructs the intake queue and its single worker exactly once, wires the
  worker's target to the existing (unmodified) `CommittedBarOrchestrator
  .process`, adds one new required configuration field
  (`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY`), and documents the fixed,
  non-configurable worker count of exactly one.

## What Does Not Change

- `CommittedBarOrchestrator.process` (`utility/committed_bar/orchestrator.py`)
  is called with the exact same signature and exact same semantics: catalog
  snapshot, deployment selection, ascending `strategy_instance_id` sort,
  sequential per-instance dispatch, per-unit failure isolation. This change
  only replaces *what calls it* (a queue worker instead of a
  `BackgroundTasks` callback) — not what it does.
- `StrategyRuntimeOrchestrator`, `EntryReconciliationOrchestrator`, the ABI
  open-position and entry-package contracts, the Strategy Engine live-entry
  and open-trade contracts, and `StrategyInstanceRuntimeState` are
  untouched.
- `StrategyInstanceKeyedMutexRegistry` and its semantics are untouched — it
  remains the only correctness guarantee for concurrent same-instance
  writers, exactly as before.
- The first-fill endpoint (`PUT .../first-fill`) keeps its synchronous HTTP
  contract, keeps calling `AbiExecutionEventOrchestrator.process(event)`
  directly (no queue), and keeps sharing the same `state_repository` and
  `keyed_mutex_registry` objects it shares today. This change does not
  introduce any new lock, gate, or global mutex around first-fill, and does
  not serialize first-fill across different strategy instances.
- No transactional outbox, no persisted event log, no dead-letter queue, no
  event replay after restart, no retry/backoff, no configurable worker
  count, no horizontal scaling, no multi-process shared state.

## Accepted losses (Live V1)

- An accepted event still sitting in the queue when the process terminates
  is lost — no persistence, no replay on restart.
- A webhook arriving while the queue is at capacity is rejected with a
  fail-closed HTTP response; MDS's own notifier (in the companion change)
  already treats any non-success response as "attempted, logged, dropped,"
  so this is consistent end-to-end best-effort behavior, not a silent gap.
- Duplicate accepted events (e.g. from an upstream retry) are not
  deduplicated at the queue boundary — this is intentional, not an
  oversight: existing downstream idempotency (`decide_entry_reconciliation`'s
  `NoOp` path, `apply_first_fill`'s already-frozen-cycle check, and
  `StrategyRuntimeOrchestrator`'s value-equality-gated `save`) already makes
  reprocessing an identical committed bar a safe no-op, so adding a second
  dedup mechanism at the queue would duplicate existing behavior for no
  correctness benefit.

## Capabilities

### New Capabilities

- `committed-bar-intake-queue` — bounded FIFO intake queue with exactly one
  consumer worker, queue-full fail-closed behavior, and per-event failure
  isolation for accepted committed-bar events.

### Modified Capabilities

- `http-closed-bar` — the webhook handler enqueues instead of scheduling a
  `BackgroundTasks` unit; acceptance no longer implies an unbounded amount of
  concurrently-scheduled background work; a new queue-full failure mode is
  introduced alongside the existing not-ready and validation failure modes.
- `runtime-production-composition` — the composition root gains ownership of
  the intake queue and worker lifecycle, one new required configuration
  field, and an explicit, non-configurable worker-count-of-one constraint.

## Impact

- Affected code: `adapters/http/app.py` (webhook handler), a new
  `runtime/committed_bar_intake/` module (queue + worker), `config/model.py`
  and `config/loader.py` (one new field), `bootstrap/application.py`
  (composition wiring and lifespan).
- Not affected: `utility/committed_bar/`, `runtime/orchestrator/`,
  `runtime/entry_reconciliation*/`, `runtime/abi_execution_event/`,
  `runtime/coordination/keyed_mutex.py`, `runtime/state/`,
  `infrastructure/strategy_engine/`, `infrastructure/abi/`.

## Contractual dependency on `mds-runtime-committed-bar-webhook-v1`

This change treats the webhook request body as already fixed by the
existing, unmodified `http-closed-bar` contract: `instrument` (non-empty
string), `timeframe` (non-empty string), `open_time_ms` (non-negative
integer), extra fields ignored. The companion MDS change is written to
produce exactly this shape and nothing more (no strategy/deployment/OHLCV
fields). This change does not require the MDS companion change to land
first: Runtime's queue-full and validation behavior are correct and
independently testable against any caller sending a conforming request, and
Runtime places no requirement on MDS's internal delivery mechanism beyond
"at most one HTTP attempt per notification, no special headers or
authentication beyond what the endpoint already accepts today."
