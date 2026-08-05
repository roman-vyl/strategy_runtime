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
  boundary.py  CommittedBarIntakeBoundary — the one process-owned intake
               object; wraps queue.Queue[CommittedBarEvent] and exposes
               put_nowait(event), stop_accepting(), get(timeout),
               task_done() — no raw queue.Queue reference is exposed to
               callers outside this module
  worker.py    CommittedBarIntakeWorker — owns the dedicated thread and
               its not_started/running/stopping/stopped state machine;
               start()/stop_once(); drains the boundary one event at a
               time into CommittedBarOrchestrator.process

adapters/http/
  app.py       closed_bar_webhook enqueues via the boundary's
               put_nowait(...) instead of scheduling a BackgroundTasks
               unit (existing file, modified)

config/
  model.py     + committed_bar_queue_capacity field (existing file)
  loader.py    + RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY parsing (existing file)

bootstrap/
  application.py   constructs the boundary + worker, wires lifespan
                    start/stop-accepting/stop (existing file, modified)
```

## Ownership

- **Intake boundary**: `CommittedBarIntakeBoundary`, constructed exactly
  once in `build_application`, wraps one
  `queue.Queue[CommittedBarEvent](maxsize=config.committed_bar_queue_capacity)`.
  It is the *only* object either the HTTP layer or the worker holds a
  reference to — neither reaches into a raw `queue.Queue` directly (see
  "The intake boundary replaces a raw queue reference" below for why).
- **Worker**: `CommittedBarIntakeWorker` owns one `threading.Thread`
  (`daemon=False`) running a loop that is the boundary's only consumer, plus
  a small state machine (`not_started | running | stopping | stopped`, see
  "Atomic stop/start boundary" below) that makes shutdown race-free. It is
  constructed with a reference to the existing, unmodified
  `CommittedBarOrchestrator` instance (the same one `build_application`
  already constructs today) and calls `orchestrator.process(event)`
  directly — no new indirection layer between the worker and the
  orchestrator.
- **Producer**: `closed_bar_webhook` (`adapters/http/app.py`) calls
  `app.state.committed_bar_intake.put_nowait(committed_bar)`. This is
  thread-safe and non-blocking, so it can be called directly from the
  `async def` handler without `run_in_threadpool` or any executor hop.

## The intake boundary replaces a raw queue reference

A raw `queue.Queue` exposed as `app.state`'s entire public surface has no
way to refuse new work once shutdown has begun — `queue.Queue.put_nowait`
only ever fails on capacity, never on "the process is shutting down."
Without a distinct signal for that second condition, the HTTP layer would
keep accepting and enqueuing webhooks for as long as capacity allowed, even
after the worker has already been told to stop — those events would then
simply sit in the queue and be discarded at shutdown, silently, with the
caller having been told `200 accepted`.

`CommittedBarIntakeBoundary` closes that gap by owning one `threading.Lock`
(`_accept_lock`) shared by exactly two operations:

```python
class CommittedBarIntakeBoundary:
    def __init__(self, capacity: int) -> None:
        self._queue: queue.Queue[CommittedBarEvent] = queue.Queue(maxsize=capacity)
        self._accept_lock = threading.Lock()
        self._accepting = True

    def put_nowait(self, event: CommittedBarEvent) -> None:
        with self._accept_lock:
            if not self._accepting:
                raise IntakeNotAccepting()
            self._queue.put_nowait(event)  # may itself raise queue.Full

    def stop_accepting(self) -> None:
        with self._accept_lock:
            self._accepting = False

    def get(self, timeout: float) -> CommittedBarEvent:
        return self._queue.get(timeout=timeout)  # worker-only; single consumer

    def task_done(self) -> None:
        self._queue.task_done()
```

Because `put_nowait` and `stop_accepting` share `_accept_lock`, every call
to either one linearizes relative to every call to the other. For any given
webhook request, exactly one of two orderings holds:

- its `put_nowait` call acquires the lock **before** `stop_accepting` does
  — the event is genuinely enqueued (subject to the normal capacity check),
  and the caller's `200 accepted` is honest;
- `stop_accepting` acquires the lock **first** — `put_nowait` observes
  `self._accepting is False` and raises `IntakeNotAccepting` *before ever
  touching the underlying queue*, and the caller receives the existing
  `503`/`not_ready` response instead of a false `200`.

There is no third outcome where a request is accepted into the queue after
shutdown has begun.

`IntakeNotAccepting` is a distinct exception from `queue.Full` specifically
so the HTTP handler (and its logging — see "Queue-full and intake-stopped
rejections" below) can tell the two rejection reasons apart, even though
both currently produce the identical wire response.

## Atomic stop/start boundary

A naive worker loop —

```python
while not stop_flag.is_set():
    event = queue.get(timeout=0.2)
    orchestrator.process(event)
```

— has a race: `stop_flag` can be set by another thread *after* the loop's
check passes but *before* (or during) `queue.get()`, so an event can be
dequeued and start processing even though shutdown was already requested,
with no guarantee shutdown will wait for it, and no guarantee it won't. The
fix is one small state machine, guarded by one lock that is never held
across a blocking call:

```python
class _State(Enum):
    NOT_STARTED = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()

class CommittedBarIntakeWorker:
    def __init__(self, intake, orchestrator, logger) -> None:
        self._intake = intake
        self._orchestrator = orchestrator
        self._logger = logger
        self._lifecycle_lock = threading.Lock()   # short-held only
        self._stop_lock = threading.Lock()        # serializes stop_once()
        self._state = _State.NOT_STARTED
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while True:
            try:
                event = self._intake.get(timeout=0.2)
            except queue.Empty:
                with self._lifecycle_lock:
                    if self._state is not _State.RUNNING:
                        return
                continue

            with self._lifecycle_lock:
                if self._state is not _State.RUNNING:
                    # stop_once() already transitioned RUNNING -> STOPPING
                    # before this event could become "current". Discard it.
                    self._intake.task_done()
                    return
                # Still RUNNING: this exact event becomes current *before*
                # the lock is released, so any stop_once() call that
                # acquires the lock immediately afterward is guaranteed to
                # see a RUNNING state that it must wait out, not a state it
                # can transition out from under this event.
                current = event

            try:
                self._orchestrator.process(current)
            except Exception:
                self._logger.exception(
                    "committed-bar intake worker failed to process one event"
                )
            finally:
                self._intake.task_done()
```

The lifecycle lock is held only for the state check and the handoff of
`current` — never across `self._intake.get(...)` (which can block up to
0.2s) and never across `self._orchestrator.process(...)` (which can run for
as long as the current committed-bar event's fan-out takes). This is what
makes the earlier instruction — "do not hold the lifecycle lock while
`orchestrator.process` executes" — true: the lock's only job is to make the
*decision* of "does this event start" atomic with respect to `stop_once()`,
not to serialize the processing itself.

### `stop_once()` behavior, one case per starting state

```python
def stop_once(self) -> None:
    with self._stop_lock:            # only one caller ever reaches the join
        with self._lifecycle_lock:
            if self._state is _State.NOT_STARTED:
                self._state = _State.STOPPED
                return                # never call join() on an unstarted thread
            if self._state is _State.STOPPED:
                return                # already fully stopped; no-op
            # self._state is RUNNING here (STOPPING is unreachable while
            # holding _stop_lock — see below)
            self._state = _State.STOPPING
            thread = self._thread
        thread.join()                 # lock released; the worker thread may
                                       # still need _lifecycle_lock in _run()
        with self._lifecycle_lock:
            self._state = _State.STOPPED
```

- **Called before `start()`**: state is `NOT_STARTED`; transitions directly
  to `STOPPED` without ever constructing or joining a thread.
- **Called while `RUNNING`**: transitions to `STOPPING` (which `_run()` will
  observe at its next lock acquisition — either immediately, if it is idle
  in `queue.Empty` handling or between events, or after finishing whatever
  event is already current), then joins the thread, then marks `STOPPED`.
- **Called after already `STOPPED`**: no-op, immediately.
- **Called concurrently from two callers**: `_stop_lock` fully serializes
  the entire method body, so the second caller blocks on `_stop_lock`
  until the first caller has already driven the state to `STOPPED` and
  returned. The second caller then acquires `_stop_lock`, observes
  `STOPPED` under `_lifecycle_lock`, and returns without ever calling
  `thread.join()` itself — **only the first caller performs the join**.

This is why two locks exist rather than one: `_lifecycle_lock` is the
fine-grained lock the worker thread itself must acquire (briefly) inside
`_run()`, so it can never be held across `thread.join()` or the second
caller would deadlock against the very thread it's trying to join.
`_stop_lock` is the coarse lock that answers "has `stop_once()` already
been called by someone else" without needing the worker thread's
involvement at all.

## Concurrency invariants

```text
max concurrent CommittedBarOrchestrator.process calls = 1
```

This follows directly from there being exactly one consumer thread, and
from the atomic stop/start boundary above guaranteeing that at most one
event is ever "current" at a time — the next `self._intake.get(...)` call
inside `_run()` does not execute until the previous `process(...)` call
(and its `finally: self._intake.task_done()`) has already returned.

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
instances — no global state mutex is added anywhere. (The worker's own
`_lifecycle_lock`/`_stop_lock` guard only the worker's own start/stop/
current-event bookkeeping; they have no relationship to
`StrategyInstanceKeyedMutexRegistry` and are never held while any
strategy-instance critical section is open.)

## HTTP endpoint change

```python
@app.post(...)
async def closed_bar_webhook(
    request: ClosedBarRequest,
) -> AcceptedResponse | JSONResponse:
    if not app.state.ready or app.state.committed_bar_intake is None:
        return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
    try:
        committed_bar = CommittedBarEvent(
            instrument=request.instrument,
            timeframe=request.timeframe,
            open_time_ms=request.open_time_ms,
        )
        _trace_id = app.state.trace_id_factory()
        app.state.committed_bar_intake.put_nowait(committed_bar)
    except IntakeNotAccepting:
        app.state.logger.warning(
            "closed-bar rejected: intake_stopping",
            instrument=committed_bar.instrument,
            timeframe=committed_bar.timeframe,
            open_time_ms=committed_bar.open_time_ms,
        )
        return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
    except queue.Full:
        app.state.logger.error(
            "closed-bar rejected: queue_full",
            instrument=committed_bar.instrument,
            timeframe=committed_bar.timeframe,
            open_time_ms=committed_bar.open_time_ms,
            capacity=app.state.committed_bar_queue_capacity,
        )
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
into the boundary or the worker.

### Reusing `NotReadyResponse` for both rejection reasons, deliberately

Both the queue-full case and the intake-stopping case reuse the existing
`503 NotReadyResponse` envelope (`{"status": "not_ready"}`) rather than
introducing a new response model. This is a deliberate choice, not an
oversight: from the caller's perspective (MDS's notifier, per the companion
change) any non-success response is already treated identically — logged,
dropped, not retried — so a wire-level distinction between these cases and
the pre-existing "not ready" case would add a new public contract with no
corresponding consumer behavior to justify it. Operators distinguish the
causes server-side, through Runtime's logs (see the next section), not
through the HTTP response shape. If a future consumer needs to distinguish
these cases over the wire, that is a new, separately justified change — not
introduced speculatively here.

A rejected-for-capacity or rejected-for-shutdown request creates **zero**
processing work: `CommittedBarOrchestrator.process` is never invoked and no
thread is spawned for it.

## Queue-full and intake-stopped rejections are logged with distinct reasons

Both rejection paths produce the identical `503`/`not_ready` wire response,
so the HTTP handler is the sole place either is observable, and it SHALL
log them distinguishably:

- **`queue_full`**: `put_nowait` raised `queue.Full` — the boundary was
  still accepting, but had no capacity. Logged at `ERROR`, containing
  `instrument`, `timeframe`, `open_time_ms`, and the configured
  `committed_bar_queue_capacity`.
- **`intake_stopping`** (also acceptable: `not_accepting`): `put_nowait`
  raised `IntakeNotAccepting` — `stop_accepting()` had already run.
  Logged at `WARNING` (this is an expected, not exceptional, consequence of
  an in-progress shutdown, unlike `queue_full` which signals undersized
  capacity), containing the same `instrument`/`timeframe`/`open_time_ms`.

The worker thread logs nothing extra for either rejection — it has no
visibility into requests it never received; the HTTP layer is the sole
point where either rejection is observed and must be logged.

## Per-event failure isolation

Failure isolation is unchanged in substance from the atomic-boundary
pseudocode already shown above under "Atomic stop/start boundary":
`CommittedBarOrchestrator.process` already isolates *per-strategy-instance*
dispatch failures internally (`StrategyCycleDispatchOutcome.failed(...)`,
recorded via `JsonlProcessingJournal`) and only raises out of `process(...)`
for an upstream preparation failure (`CommittedBarPreparationError` — a
`deployment_catalog` or `deployment_selection` failure before any instance
was dispatched, per the existing `committed-bar-orchestrator` capability).
The worker's own `try`/`except` around `process(...)` exists specifically to
survive that outer failure mode: one event whose catalog load or selection
raises is logged and the loop continues to the next queued event (dequeued
through the same atomic check) without the worker thread dying. This is the
same "log through the existing journal/error boundary, keep processing"
posture already established for per-instance failures — this change extends
it one layer up, to the whole-event level, without inventing a second
journaling mechanism.

## FIFO and duplicate handling

The boundary preserves plain FIFO ordering (`queue.Queue`'s native
ordering) — accepted events are processed in the exact order they were
enqueued. No deduplication is performed at the boundary: a duplicate
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
thread exactly once and transitions `NOT_STARTED -> RUNNING`; calling it a
second time is not a supported operation.

### Shutdown sequence

Shutdown is three ordered steps, not a single call:

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    intake_worker.start()
    try:
        yield
    finally:
        intake.stop_accepting()
        await asyncio.to_thread(intake_worker.stop_once)
        lifecycle.close_all_once()
```

1. **`intake.stop_accepting()`** — synchronous, instantaneous (one lock
   acquisition). From this point, every new webhook request is rejected
   with `intake_stopping` (see above); no further event can enter the
   boundary. This runs directly on the event-loop thread — it never blocks.
2. **`await asyncio.to_thread(intake_worker.stop_once)`** — offloaded to a
   thread because `stop_once()` can call `thread.join()`, which is a
   blocking call with no bound of its own (see "Shutdown's actual bound" and
   "Do not block the event loop during join" below). Awaiting the
   offloaded call still means this coroutine does not proceed to step 3
   until `stop_once()` has fully returned, but it does **not** block the
   event loop's other work while waiting — other scheduled coroutines
   continue to run on the loop during this wait.
3. **`lifecycle.close_all_once()`** — closes the four shared outbound HTTP
   clients. This step only runs after step 2's `await` has completed, i.e.
   only after the worker thread has fully exited (any event that was
   `current` when `stop_accepting()`/`stop_once()` ran has already finished,
   successfully or by raising). This ordering is required, not incidental:
   closing those clients before the worker thread has exited could let its
   still-in-flight `orchestrator.process(...)` call observe an
   already-closed client.

### Do not block the event loop during join

FastAPI's lifespan is an async context manager running on the event loop.
Calling `intake_worker.stop_once()` directly (unwrapped) from `_lifespan`
would call a potentially long, purely synchronous `Thread.join()` on the
event-loop thread itself, blocking every other coroutine scheduled on that
loop for the duration — the same class of problem this change's MDS-facing
`asyncio.to_thread` usage (in the companion change) exists to avoid, now on
the Runtime side during shutdown. `await asyncio.to_thread(intake_worker
.stop_once)` offloads the call to a worker thread from the interpreter's
thread pool, so the event loop remains free to run other scheduled
coroutines while this coroutine awaits that offloaded call's completion.

### Shutdown's actual bound — an accepted tradeoff, not a hang-proof guarantee

Clean shutdown deliberately waits for whichever one committed-bar event was
`current` at the moment shutdown began (if any) to finish, rather than
interrupting it. That wait's *network* portion is bounded by the existing,
already-configured, finite outbound timeouts each downstream adapter call
already enforces (`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`), multiplied by however many
sequential per-instance dispatches remain in that one committed-bar event's
fan-out.

This change does **not** claim that those finite HTTP timeouts make the
untimed `thread.join()` provably safe against ever hanging. They bound only
the *network* operations inside `process(...)`. Local work inside the same
call — deployment-catalog file access, acquiring
`StrategyInstanceKeyedMutexRegistry`'s per-instance lock, in-memory
repository reads/writes, or an unanticipated defect (an infinite loop, a
deadlock elsewhere in the call graph) — is given **no new hard deadline** by
this change. The worker layer introduces no forced interruption and no hard
shutdown timeout of its own: if the current event's local work never
returns, `stop_once()`'s `thread.join()` genuinely waits forever, and so
does the `await asyncio.to_thread(...)` in `_lifespan`.

This is an accepted clean-shutdown tradeoff for Live V1, not a proven
safety property: the alternative (a hard shutdown timeout that abandons the
worker thread) would risk closing the four shared outbound HTTP clients
while that thread is still using one of them — a worse, silent-corruption
-shaped failure mode than a shutdown that occasionally takes longer than
expected. No forced-interruption or hard-timeout mechanism is introduced by
this change to close that gap; if a real production need for one is later
observed, it is a separate, explicitly scoped decision.

`stop_once()` remains idempotent as already specified above: a second call,
after the first has already driven the state to `STOPPED`, is a no-op.

When `build_application` fails partway through construction (the existing
startup-rollback path), the intake worker is either never started (if
failure occurs before its construction step) or is stopped — following the
exact same shutdown sequence above, `stop_accepting` then `stop_once` then
client-close — as part of the same rollback path that already closes the
four outbound HTTP clients. No `ready=True` application is ever returned
with a worker that wasn't properly started, and no `ready=False`
application is ever returned with an orphaned running worker thread.

## Configuration

`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` follows the existing `RuntimeConfig`/
`load_runtime_config` pattern exactly: a required, validated positive
integer, parsed with the same `_require_...`-style helper already used for
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS` and friends, checked in
`RuntimeConfig.__post_init__` alongside the existing `RUNTIME_PORT` bounds
check. Default used in deployment examples and documentation: **256**.

### Capacity is required and positive; no comfortable-coverage claim is made

The boundary holds raw accepted `CommittedBarEvent`s, not per-strategy
-instance dispatch tickets — one webhook occupies one slot regardless of how
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
repository) and is out of scope for this change. The intake boundary and its
worker are process-local Python objects (`queue.Queue`, `threading.Thread`,
`threading.Lock`); running more than one Runtime process or worker would
give each its own independent boundary with no coordination between them,
exactly mirroring the pre-existing, already-documented constraint on
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
