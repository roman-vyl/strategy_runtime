# Design: Bounded Committed-Bar Intake v1

## Context

`StrategyRuntimeOrchestrator.process` and `AbiExecutionEventOrchestrator
.process` are both plain synchronous methods, and the keyed-mutex registry
they share is built on `threading.Lock`, not `asyncio.Lock`.
`CommittedBarOrchestrator.process`, which calls
`StrategyRuntimeOrchestrator.process` once per selected instance, is
therefore also synchronous end-to-end for its per-instance dispatch. A
single dedicated OS thread — not an `asyncio.Queue` consumer — is what
makes "process one committed-bar event fully before starting the next"
correct, because the underlying critical sections are thread-blocking, not
`await`-cooperative.

## Architecture

```text
runtime/committed_bar_intake/
  boundary.py  CommittedBarIntakeBoundary — the one process-owned intake
               object; wraps a bounded queue.Queue[CommittedBarEvent]
  worker.py    CommittedBarIntakeWorker — owns the dedicated consumer
               thread and its start/stop state machine

adapters/http/app.py     webhook enqueues via the boundary (existing file)
config/{model,loader}.py + committed_bar_queue_capacity (existing files)
bootstrap/application.py constructs boundary + worker, wires lifespan
```

- **Intake boundary**: constructed exactly once in `build_application`,
  wraps one bounded `queue.Queue`. It is the *only* object either the HTTP
  layer or the worker holds a reference to — no raw `queue.Queue` is ever
  exposed outside it (normative: `committed-bar-intake-queue`).
- **Worker**: owns one non-daemon thread that is the boundary's only
  consumer, plus a small state machine that makes shutdown race-free
  (normative: `committed-bar-intake-queue`). Constructed with a reference
  to the existing, unmodified `CommittedBarOrchestrator` instance and
  calls `orchestrator.process(event)` directly.
- **Producer**: the webhook handler calls the boundary's `put_nowait`
  directly from its `async def` handler — thread-safe and non-blocking,
  no executor hop needed.

## Why a boundary object, not a raw queue

A raw `queue.Queue` has no way to refuse new work once shutdown has begun
— `put_nowait` only ever fails on capacity, never on "the process is
shutting down." Without a distinct signal for that, the HTTP layer would
keep enqueuing after the worker was told to stop, and those events would
be silently discarded at shutdown despite the caller having been told
`200 accepted`. The boundary closes that gap with one lock shared between
`put_nowait` and `stop_accepting`, so the two linearize: a given
`put_nowait` either wins the race and genuinely enqueues, or
`stop_accepting` wins first and it is rejected with a distinct exception
before ever touching the queue. There is no third outcome — normative
scenarios live in `committed-bar-intake-queue`.

## Why the worker's start/stop is a small state machine, not a flag

A naive loop that checks a stop flag before each blocking dequeue has a
race: the flag can flip between the check and the dequeue, so an event can
start processing after shutdown was already requested with no guarantee
either way about whether shutdown waits for it. The fix is a lock-guarded
state machine where "does this dequeued event become current" and "has
`stop_once()` already moved to stopping" are decided under the same
short-held lock — never held across the blocking dequeue or across
`orchestrator.process(...)` itself, only across the current-event
decision. Whichever side wins that lock acquisition determines the
outcome deterministically: the event either becomes current and is
guaranteed to run to completion, or shutdown wins and the event is
discarded before ever reaching the orchestrator.

`start()` publishes `running` and starts the real thread as one atomic
step under that same lock, so `stop_once()` can never observe `running`
before the underlying OS thread has actually started (which would
otherwise let it attempt to join a thread that was never really started).
If the thread fails to start, the worker lands in `stopped`, not left
`running` or `stopping`, and the original error is re-raised. Full
state-by-state behavior, `stop_once()`'s idempotency, and its behavior
under concurrent callers are normative in `committed-bar-intake-queue`.

## Concurrency invariants

- At most one `CommittedBarOrchestrator.process` call is ever in flight —
  exactly one consumer thread, and the state machine above guarantees at
  most one event is ever current.
- Per strategy instance, at most one state-writing critical section is
  open at a time, via the existing, unmodified
  `StrategyInstanceKeyedMutexRegistry` — unaffected by this change. The
  intake worker thread and a first-fill request thread block on the same
  per-key lock when they target the same instance.
- A first-fill request for a *different* instance is never blocked by the
  intake worker processing any event — different instance keys use
  different locks, and this change adds no lock that spans instances.

## Rejection logging

Both `queue_full` and `intake_stopping` reuse the existing `503
not_ready` wire envelope deliberately — MDS's notifier already treats any
non-success response identically (logged, dropped, not retried), so a
wire-level distinction would add a new public contract with no consumer
behavior to justify it. Operators distinguish the two causes through
Runtime's server-side logs instead; normative fields are specified in
`http-closed-bar`.

## Shutdown

Shutdown is `stop_accepting()` (synchronous, one lock acquisition, never
blocks) → offloaded `stop_once()` (via `asyncio.to_thread`, so the
FastAPI event loop is not blocked by the worker's join) → outbound-client
close, in that order, with `intake_worker.start()` itself inside the
lifespan's `try` so a startup failure still runs this full cleanup instead
of leaking a worker or clients. Normative behavior, including the
pending-vs-current-event split and the client-close ordering, lives in
`committed-bar-intake-queue` and `runtime-production-composition`.

Clean shutdown deliberately waits for the one already-current event
rather than interrupting it. Its network operations are bounded by the
existing finite Engine/ABI timeouts; its local work (catalog access,
mutex waits, repository operations, or an unanticipated defect) is not
given any new deadline by this change — an accepted Live V1 tradeoff. The
alternative (a hard timeout that abandons the worker thread) risks
closing shared outbound clients while that thread is still using one — a
worse, silent-corruption-shaped failure than an occasionally slow
shutdown.

## Configuration

`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` follows the existing `RuntimeConfig`
pattern: required, validated positive integer, checked in
`RuntimeConfig.__post_init__`. The boundary additionally validates its
own `capacity` locally (positive `int`, `bool` excluded) before
constructing the queue, since `queue.Queue(maxsize<=0)` silently means
"unbounded" — a local invariant of the boundary, independent of and in
addition to the production configuration gate.

Worker count is fixed at exactly one and is not configurable — the entire
correctness argument above depends on there being exactly one consumer
thread; making it configurable would let an operator silently opt into
unreviewed concurrent-orchestrator-call semantics.

Capacity sizing is an operator responsibility, not a value this design
proves sufficient for every deployment: the queue holds one slot per
accepted webhook regardless of downstream fan-out, so the realistic worst
case is bounded by how many distinct MDS streams (`instrument ×
timeframe` pairs) can commit within the same short window at a shared
boundary (top of hour, midnight UTC), not by strategy-instance count.
Operators should configure capacity at least as large as their maximum
expected MDS burst, normally no smaller than their enabled stream count;
`256` is a generous starting point for small-to-medium catalogs,
documented in the canonical example, not a value proven sufficient for
every deployment.

## Single-process / single-worker limitation

This change adds no code-level guard against `uvicorn --workers N > 1` or
multiple replicas — that gap already exists and is out of scope. The
intake boundary and worker are process-local objects; running more than
one process or worker gives each its own independent, uncoordinated
boundary, mirroring the pre-existing, already-documented "no
cross-process guarantee" constraint on `StrategyInstanceKeyedMutexRegistry`.

## Cross-timeframe (HTF) consistency

Confirmed, not a dependency: the Strategy Engine's live-entry path reads
exactly one base-timeframe candle stream per evaluation and does not
depend on independently-committed higher-timeframe MDS streams at
evaluation time. This change introduces no cross-timeframe barrier and
closes no confirmed gap, since none exists.

## Rejected alternatives

- **Expose the raw `queue.Queue` on `app.state`**: no way to signal
  "shutting down" distinctly from "at capacity."
- **A stop flag checked before each dequeue**: races against a concurrent
  `stop_once()`.
- **A hard shutdown timeout that abandons the worker thread**: risks
  closing outbound clients while still in use by that thread.
- **A configurable worker count**: the single-worker concurrency
  guarantee is a safety property, not a performance knob.
- **A durable/replayable intake queue**: the state repository behind it
  is already non-durable in Live V1, so durability would stop at the
  queue boundary without an end-to-end guarantee.
