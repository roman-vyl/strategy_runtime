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
returns the `503`/`not_ready` response described above. Because the wire
response for this case is the generic, pre-existing `NotReadyResponse`
envelope (deliberately not a new public contract — see "Reusing
`NotReadyResponse`" above), the HTTP handler SHALL also emit one
server-side log line for the rejection, at the point it catches `queue.Full`,
containing exactly `instrument`, `timeframe`, `open_time_ms` (from the
already-validated `committed_bar` that failed to enqueue), and the
configured `committed_bar_queue_capacity` — this is the only place an
operator can distinguish a queue-full rejection from a startup-not-ready
rejection, since both currently produce the identical wire response. The
worker thread logs nothing extra for a rejection that never reached the
queue — it has no visibility into requests it never received; the HTTP
layer is the sole point where a full-queue rejection is observed and must
be logged.

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

`CommittedBarIntakeWorker.start()` spawns the single, non-daemon consumer
thread exactly once; calling it a second time is not a supported operation
(mirrors `_OutboundHttpClientLifecycle`'s single-owner posture — there is
exactly one call site).

### Clean-shutdown contract

A non-daemon thread executing `CommittedBarOrchestrator.process(event)` —
a synchronous, potentially multi-instance-fan-out call — cannot be
interrupted mid-call by setting a `threading.Event`. The event is only
observed at the worker's own loop boundary, *after* whatever call is
currently running has already returned. Shutdown is therefore defined as a
fixed sequence, not a fixed time bound:

1. FastAPI lifespan shutdown calls `intake_worker.stop_once()`.
2. `stop_once()` sets an internal stop flag. From this point, the worker
   will not start processing any further queued item, however many remain.
3. Any event still sitting in the queue, not yet dequeued, is discarded —
   the worker does not drain or process it.
4. If one event is currently being processed
   (`orchestrator.process(event)` already running) when the stop flag is
   set, shutdown does **not** interrupt it: `stop_once()` blocks until that
   specific call returns, whether it returns normally or raises.
5. Once the worker thread has fully exited — the current event (if any)
   finished, no next event started, the thread function returned — and
   only then, do the four shared outbound HTTP clients (Strategy Engine
   live-entry/open-trade, ABI open-position/entry-package) get closed via
   the existing `lifecycle.close_all_once()`. This ordering is required,
   not incidental: closing those clients while the worker thread might
   still be mid-call, using one of them to finish its current event, would
   be a lifecycle violation — an in-flight call could observe a closed
   client.

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    intake_worker.start()
    try:
        yield
    finally:
        intake_worker.stop_once()  # blocks until the worker thread has
                                    # fully exited (steps 1-5 above) before
                                    # returning
        lifecycle.close_all_once()
```

### `stop_once()` joins without an arbitrary bounded timeout

`stop_once()` sets the stop flag, then calls `self._thread.join()` with
**no timeout** — not a small, arbitrary bounded one. A bounded join (for
example, a fixed few-hundred-millisecond timeout) would be incorrect here:
`Thread.join(timeout=...)` can return while the thread is still alive, and
if `stop_once()` treated that return as "stopped," `lifecycle
.close_all_once()` could run concurrently with the worker's still-in-flight
outbound calls.

Clean shutdown's real bound is **not** the worker's idle-poll interval
(`queue.get(timeout=0.2)`, which only bounds how quickly an *idle* worker
notices the stop flag) — it is the completion time of whatever
`orchestrator.process(event)` call happens to be running when shutdown
begins. That, in turn, is bounded by the existing, already-configured,
finite outbound timeouts each downstream adapter call already enforces
(`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`), multiplied by however many
sequential per-instance dispatches remain in that one committed-bar event's
fan-out. This change introduces no new timeout of its own — it relies
entirely on those existing, already-enforced outbound timeouts to guarantee
the current event eventually finishes (successfully or by raising) and the
thread exits, which is what makes an untimed `join()` safe rather than a
risk of hanging forever.

`stop_once()` is idempotent (mirrors `_OutboundHttpClientLifecycle
.close_all_once`'s existing pattern): a second call, after the first has
already joined the thread, is a no-op — it does not attempt to join an
already-exited thread a second time and does not raise.

When `build_application` fails partway through construction (the existing
startup-rollback path), the intake worker is either never started (if
failure occurs before its construction step) or is stopped — following the
exact same clean-shutdown contract above, worker-join before client-close —
as part of the same rollback path that already closes the four outbound
HTTP clients. No `ready=True` application is ever returned with a worker
that wasn't properly started, and no `ready=False` application is ever
returned with an orphaned running worker thread.

## Configuration

`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` follows the existing `RuntimeConfig`/
`load_runtime_config` pattern exactly: a required, validated positive
integer, parsed with the same `_require_...`-style helper already used for
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS` and friends, checked in
`RuntimeConfig.__post_init__` alongside the existing `RUNTIME_PORT` bounds
check. Default used in deployment examples and documentation: **256**.

### Capacity is required and positive; no comfortable-coverage claim is made

The queue holds raw accepted `CommittedBarEvent`s, not per-strategy-instance
dispatch tickets — one webhook occupies one queue slot regardless of how
many strategy instances its deployment selection later fans out to. The
realistic worst case this queue must absorb is therefore bounded by how many
*distinct MDS streams* (`instrument × timeframe` pairs) can commit within
the same short window at a shared boundary (top of hour, four hours,
midnight), not by strategy-instance count.

This design does **not** claim that any specific default number
"comfortably covers" a particular catalog size (for example, "a few dozen
instruments across six timeframes") — `strategy_runtime` has no visibility
into MDS's actual configured instrument/timeframe count, and asserting a
specific default is sufficient for an unknown catalog would be an
unsupported claim. The operational rule instead is: **operators SHALL
configure `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` at least as large as the
maximum expected MDS boundary burst for their deployment, normally no
smaller than the number of MDS enabled streams** (`instrument × timeframe`
pairs) — since a shared boundary (midnight UTC, worst case) can produce one
webhook per enabled MDS stream within a short window. `256` is documented
in deployment examples as a generous starting point for small-to-medium
catalogs, not a value this design proves sufficient for every deployment;
operators with a larger catalog are expected to raise it explicitly via
`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY`. This mirrors the equivalent default
and equivalent operator-sizing responsibility documented for MDS's own
outbound queue in the companion change.

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

## Findings: cross-timeframe (HTF) consistency — confirmed, not a dependency

Earlier exploration for this change established that `strategy_runtime`
itself carries only one `base_timeframe`/`target_bar_open_time_ms` pair per
outbound Engine request
(`infrastructure/strategy_engine/http_projection_client.py`), and that
`CommittedBarDeploymentSelector.select` filters strictly on
`deployment.base_timeframe == event.timeframe` — a webhook for `1h` never
triggers a strategy instance configured with `base_timeframe="5m"`, and vice
versa.

The remaining open question — whether the Strategy Engine derives
higher-timeframe features internally from a single base-timeframe candle
stream, or instead depends at evaluation time on independently-committed HTF
MDS streams — has since been resolved by inspecting the Strategy Engine
repository's live-entry path directly. `LoadLiveFeatureFrame` constructs
exactly one `MarketStream(ticker, base_timeframe)` and calls
`EvaluateIndicatorRange`, which performs exactly one
`MarketDataPort.load_range(request.market, requested_range)` call before
handing the already-loaded `MarketFrame` to the evaluator; the evaluator
itself has no `MarketDataPort` dependency in this use case. This confirms
that live-entry evaluation reads exactly one base-timeframe candle stream
through one load call, and does **not** read independently committed
1h/4h/1d MDS streams at evaluation time.

Combined, this means the arrival order of independently committed
higher-timeframe MDS streams relative to a lower-timeframe commit is
**not** a correctness dependency of the current Engine live-entry path.
This change introduces no cross-timeframe barrier, fixed sleep, or boundary
coordinator, and no follow-up cross-timeframe-readiness change is proposed
from this change or its MDS companion — there is no confirmed gap for one
to close. Moving from `BackgroundTasks` to a FIFO queue with one worker does
not change this conclusion either way: it only bounds concurrency and
orders already-accepted events, and neither introduces nor removes any
dependency on cross-timeframe MDS stream arrival order. No Strategy Engine
code or specs are modified by this change or by this finding.
