# Design: Bounded Committed-Bar Intake v1

## Context

`StrategyRuntimeOrchestrator.process` (`runtime/orchestrator/orchestrator.py:46`)
and `AbiExecutionEventOrchestrator.process`
(`runtime/abi_execution_event/orchestrator.py:21`) are both plain
**synchronous** methods, and the keyed-mutex registry they share
(`runtime/coordination/keyed_mutex.py`) is built on `threading.Lock`, not
`asyncio.Lock`. `CommittedBarOrchestrator.process`
(`utility/committed_bar/orchestrator.py:43`), which calls
`StrategyRuntimeOrchestrator.process` once per selected instance via
`StrategyCycleHandoffBoundary`/`process_strategy_cycle`
(`bootstrap/application.py:184-195`), is therefore also effectively
synchronous end-to-end for its per-instance dispatch. The intake design
below is built around that fact: a single dedicated OS thread, not a naive
`asyncio.Queue` consumer, is what makes "process one committed-bar event
fully before starting the next" a correct implementation of "one worker,"
because the underlying critical sections are thread-blocking, not
`await`-cooperative.

## Module decomposition

```text
runtime/committed_bar_intake/
  queue.py     BoundedCommittedBarIntakeQueue — thin wrapper over
               queue.Queue[CommittedBarEvent] with a fixed maxsize
  worker.py    CommittedBarIntakeWorker — owns the dedicated thread,
               start()/stop_once(), drains the queue one event at a
               time into CommittedBarOrchestrator.process

adapters/http/
  app.py       closed_bar_webhook enqueues instead of scheduling a
               BackgroundTasks unit (existing file, modified)

config/
  model.py     + committed_bar_queue_capacity field (existing file)
  loader.py    + RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY parsing (existing file)

bootstrap/
  application.py   constructs the queue + worker, wires lifespan
                    start/stop (existing file, modified)
```

## Ownership

- **Queue**: `queue.Queue[CommittedBarEvent](maxsize=config
  .committed_bar_queue_capacity)`, constructed exactly once in
  `build_application`, owned exclusively by `CommittedBarIntakeWorker`. The
  HTTP layer holds only a reference sufficient to call `put_nowait`; it does
  not own the queue's lifecycle.
- **Worker**: `CommittedBarIntakeWorker` owns one `threading.Thread`
  (`daemon=False`, explicitly joined on shutdown — see "Lifecycle" below)
  running a loop that is the queue's only consumer. It is constructed with a
  reference to the existing, unmodified `CommittedBarOrchestrator` instance
  (the same one `build_application` already constructs today) and calls
  `orchestrator.process(event)` directly — no new indirection layer between
  the worker and the orchestrator.
- **Producer**: `closed_bar_webhook` (`adapters/http/app.py`) calls
  `app.state.committed_bar_intake_queue.put_nowait(committed_bar)`. This is
  thread-safe and non-blocking (`queue.Queue`'s internal lock never blocks
  on `put_nowait`), so it can be called directly from the `async def`
  handler without `run_in_threadpool` or any executor hop.

## Concurrency invariants

```text
max concurrent CommittedBarOrchestrator.process calls = 1
```

This follows directly from there being exactly one consumer thread running
a strictly sequential `while not stopped: event = queue.get(); orchestrator
.process(event)` loop — never a thread pool, never `asyncio.gather`, never a
second worker. The next `queue.get()` does not return until the previous
`process(...)` call has returned (successfully or by raising, see "Per
-event failure isolation" below).

```text
per strategy instance: max concurrent state-writing critical sections = 1
  (via the existing, unmodified StrategyInstanceKeyedMutexRegistry)
```

Unaffected by this change. The intake worker thread and the FastAPI
threadpool thread handling a first-fill request are two independent OS
threads that both, when they reach a same-`strategy_instance_id` critical
section, block on the same `threading.Lock` obtained from the same shared
`StrategyInstanceKeyedMutexRegistry` instance
(`runtime-production-composition`'s existing "exactly one shared... registry"
guarantee) — exactly the interleaving already proven by the existing
`tests/integration/http/test_first_fill_shared_writer_serialization.py`,
which needs no modification because it asserts blocking-on-lock behavior
independent of which caller (background task vs. intake worker thread)
triggered the closed-bar side.

```text
first-fill for a different strategy instance is not blocked by the intake
worker processing any committed-bar event
```

Different `strategy_instance_id` keys use different `threading.Lock`
objects (`StrategyInstanceKeyedMutexRegistry.hold`), so a first-fill request
for instance B proceeds immediately even while the intake worker holds
instance A's lock. This change introduces no new lock that spans multiple
instances — no global state mutex is added anywhere.

## HTTP endpoint change

```python
@app.post(...)
async def closed_bar_webhook(
    request: ClosedBarRequest,
) -> AcceptedResponse | JSONResponse:
    if not app.state.ready or app.state.committed_bar_intake_queue is None:
        return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
    try:
        committed_bar = CommittedBarEvent(
            instrument=request.instrument,
            timeframe=request.timeframe,
            open_time_ms=request.open_time_ms,
        )
        _trace_id = app.state.trace_id_factory()
        app.state.committed_bar_intake_queue.put_nowait(committed_bar)
    except queue.Full:
        return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
    except Exception:
        app.state.logger.exception("Failed to accept closed-bar webhook")
        return JSONResponse(status_code=500, content={"status": "error"})
    return AcceptedResponse()
```

`BackgroundTasks` is removed from this handler's parameters entirely — there
is no longer a per-request background unit. `_trace_id` continues to be
generated and discarded, matching the existing, unmodified "Runtime reserves
an internal trace hook" requirement — this change does not plumb `trace_id`
into the queue or the worker.

### Reusing `NotReadyResponse` for queue-full, deliberately

The queue-full case reuses the existing `503 NotReadyResponse` envelope
(`{"status": "not_ready"}`) rather than introducing a new response model.
This is a deliberate choice, not an oversight: from the caller's
perspective (MDS's notifier, per the companion change) any non-success
response is already treated identically — logged, dropped, not retried — so
a wire-level distinction between "not ready" and "queue full" would add a
new public contract with no corresponding consumer behavior to justify it.
Operators distinguish the two causes server-side, through Runtime's logs
(the worker/queue emits its own diagnostic on a full-queue rejection,
distinct from the readiness-gate log path), not through the HTTP response
shape. If a future consumer needs to distinguish these cases over the wire,
that is a new, separately justified change — not introduced speculatively
here.

A rejected-for-capacity request creates **zero** processing work: the event
is never constructed into a queue item, `CommittedBarOrchestrator.process`
is never invoked, and no thread is spawned — this differs from today's
behavior only in that today's endpoint has no rejection path at all for this
condition (every accepted request always got a `BackgroundTasks` unit,
however many were already in flight).

## Queue-full behavior

`queue.put_nowait(...)` raises `queue.Full` synchronously when the queue is
at `committed_bar_queue_capacity`. The handler catches exactly this
exception (not a bare `except Exception`, so a real construction error in
`CommittedBarEvent(...)` still falls through to the existing `500` path) and
returns the `503`/`not_ready` response described above. The worker thread
logs nothing extra for a rejection that never reached the queue — the HTTP
layer is the sole point where a full-queue rejection is observed and
logged, since the worker has no visibility into requests it never received.

## Per-event failure isolation

```python
def _run(self) -> None:
    while not self._stop_event.is_set():
        try:
            event = self._queue.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            self._orchestrator.process(event)
        except Exception:
            self._logger.exception(
                "committed-bar intake worker failed to process one event"
            )
        finally:
            self._queue.task_done()
```

`CommittedBarOrchestrator.process` already isolates *per-strategy-instance*
dispatch failures internally (`StrategyCycleDispatchOutcome.failed(...)`,
recorded via `JsonlProcessingJournal`) and only raises out of `process(...)`
for an upstream preparation failure (`CommittedBarPreparationError` — a
`deployment_catalog` or `deployment_selection` failure before any instance
was dispatched, per the existing `committed-bar-orchestrator` capability).
The worker's own `try`/`except` around `process(...)` exists specifically to
survive that outer failure mode: one event whose catalog load or selection
raises is logged and discarded, and the loop continues to the next queued
event without the worker thread dying. This is the same "log through the
existing journal/error boundary, keep processing" posture already
established for per-instance failures — this change extends it one layer
up, to the whole-event level, without inventing a second journaling
mechanism.

## FIFO and duplicate handling

The queue is a plain FIFO (`queue.Queue`'s native ordering) — accepted
events are processed in the exact order they were enqueued. No
deduplication is performed at the queue boundary: a duplicate
`CommittedBarEvent` (same `instrument`/`timeframe`/`open_time_ms`, e.g. from
an MDS-side retry or a race) is enqueued and processed exactly like any
other event, and the existing downstream idempotency
(`decide_entry_reconciliation`'s `NoOp` path when the desired entry is
unchanged, `apply_first_fill`'s already-frozen-cycle short-circuit, and
`StrategyRuntimeOrchestrator`'s value-equality-gated `state_repository.save`)
already makes reprocessing a no-op. No new deduplication database, cache, or
in-memory set is introduced by this change.

## Lifecycle

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    intake_worker.start()
    try:
        yield
    finally:
        intake_worker.stop_once()
        lifecycle.close_all_once()
```

`CommittedBarIntakeWorker.start()` spawns the single consumer thread exactly
once; calling it a second time is not a supported operation (mirrors
`_OutboundHttpClientLifecycle`'s single-owner posture — there is exactly one
call site). `stop_once()` sets an internal `threading.Event`, then joins the
worker thread with a bounded timeout; a second call to `stop_once()` is a
no-op (idempotent, matching `_OutboundHttpClientLifecycle.close_all_once`'s
existing idempotency pattern exactly). Because the worker's loop polls
`queue.get(timeout=0.2)` rather than blocking indefinitely, it observes the
stop event within a bounded, small delay and exits promptly — shutdown does
not hang waiting for the queue to drain, and any event still sitting in the
queue at shutdown is discarded, not processed and not persisted.

When `build_application` fails partway through construction (the existing
startup-rollback path), the intake worker is either never started (if
failure occurs before its construction step) or is stopped via the same
rollback path that already closes the four outbound HTTP clients — no
`ready=True` application is ever returned with a worker that wasn't
properly started, and no `ready=False` application is ever returned with an
orphaned running worker thread.

## Configuration

`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` follows the existing `RuntimeConfig`/
`load_runtime_config` pattern exactly: a required, validated positive
integer, parsed with the same `_require_...`-style helper already used for
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS` and friends, checked in
`RuntimeConfig.__post_init__` alongside the existing `RUNTIME_PORT` bounds
check. Default: **64**.

### Why 64

The queue holds raw accepted `CommittedBarEvent`s, not per-strategy-instance
dispatch tickets — one webhook occupies one queue slot regardless of how
many strategy instances its deployment selection later fans out to. The
realistic worst case this queue must absorb is therefore bounded by how many
*distinct MDS streams* (`instrument × timeframe` pairs) can commit within
the same short window at a shared boundary (top of hour, four hours,
midnight), not by strategy-instance count. A production deployment tracking
on the order of a few dozen instruments across MDS's six canonical
timeframes (`1m, 5m, 15m, 1h, 4h, 1d`) yields a boundary burst on the order
of several dozen simultaneous commits at worst (most timeframes do not
co-close with each other except at shared boundaries). 64 covers that
comfortably with headroom while remaining a small, bounded, fixed-cost
allocation — consistent with the equivalent default chosen for MDS's
outbound queue in the companion change, so neither side of the pipe is
structurally more likely to be the bottleneck than the other. This is a
starting default, not a tuned production value; operators with a
significantly larger catalog should raise it via
`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` rather than the code changing.

### Worker count is fixed at 1, not configurable

No `RUNTIME_COMMITTED_BAR_WORKER_COUNT` (or equivalent) setting is
introduced. This is deliberate: the entire correctness argument in this
design ("at most one `CommittedBarOrchestrator.process` call in flight")
depends on there being exactly one consumer thread. Making worker count
configurable would let an operator silently opt into an unreviewed,
untested concurrent-orchestrator-calls semantics — the fixed value of one
is a safety property of this change, not a performance knob.

## Single-process / single-worker limitation

This change does not add, remove, or enforce any code-level guard against
running Runtime with `uvicorn --workers N > 1` or multiple replicas — that
gap already exists today (confirmed: no such guard exists anywhere in the
repository) and is out of scope for this change. The intake queue and its
worker are process-local Python objects (`queue.Queue`, `threading.Thread`);
running more than one Runtime process or worker would give each its own
independent queue with no coordination between them, exactly mirroring the
pre-existing, already-documented constraint on
`StrategyInstanceKeyedMutexRegistry` ("Live V1 coordination makes no
cross-process guarantee"). This change treats that as an accepted,
already-established Live V1 boundary, not a new one it introduces.

## Findings: cross-timeframe (HTF) consistency — unresolved, out of scope

This repository cannot determine whether the Strategy Engine derives
higher-timeframe (1h/4h/1d) features internally from a single base
-timeframe candle stream, or instead depends at evaluation time on
independently-committed HTF MDS streams. Evidence gathered:

- Every outbound request this repository sends to the Strategy Engine
  (`infrastructure/strategy_engine/http_projection_client.py`) carries
  exactly one `base_timeframe` and one `target_bar_open_time_ms` — there is
  no field, and no code path, for passing or checking multiple
  simultaneously-committed timeframes.
- `CommittedBarDeploymentSelector.select` filters strictly on
  `deployment.base_timeframe == event.timeframe` — a webhook for `1h` never
  triggers a strategy instance configured with `base_timeframe="5m"`, and
  vice versa. Each deployment reacts only to its own configured timeframe's
  webhook.
- The Strategy Engine's internal candle-reading and readiness/coverage
  logic, if any, lives entirely in a separate service/repository that this
  investigation did not have access to.

Because this change only bounds *how many* accepted committed-bar events are
processed concurrently and *in what order they were accepted* (FIFO), it
does not alter whether a `5m` webhook for `BTCUSDT.P` could be processed
(and reach the Engine) before a co-closing `1h` webhook for the same
instrument is enqueued or processed — that ordering question is unaffected
by moving from `BackgroundTasks` to a FIFO queue with one worker, since
`BackgroundTasks` was also effectively concurrent/unordered across different
webhook requests today. This change deliberately adds no cross-timeframe
barrier, fixed sleep, or boundary coordinator to address a correctness
question it cannot verify. If a real correctness gap is later confirmed in
the Strategy Engine repository, it should be addressed as its own explicitly
scoped change (proposed name: `engine-cross-timeframe-readiness-v1` or
similar) — not folded into this intake-queue change or the MDS notifier
change.
