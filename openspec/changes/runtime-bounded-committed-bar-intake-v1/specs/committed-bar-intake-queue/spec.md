## ADDED Requirements

### Requirement: Runtime bounds accepted committed-bar events in one FIFO queue

Strategy Runtime SHALL hold accepted `CommittedBarEvent`s in exactly one
bounded, process-local, first-in-first-out queue between HTTP acceptance and
semantic processing, owned by one `CommittedBarIntakeBoundary` object — no
caller outside that object holds a reference to the underlying
`queue.Queue` directly.

#### Scenario: Accepted events enter the queue in order
- **WHEN** the closed-bar webhook accepts two or more valid requests while
  Runtime is ready, the intake boundary is still accepting, and the queue
  has capacity
- **THEN** each accepted event is enqueued in the order its HTTP request was
  accepted

#### Scenario: The queue has a fixed, configured capacity
- **WHEN** Runtime starts with a ready configuration
- **THEN** the intake queue's maximum size equals the validated
  `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` value
- **AND** that capacity does not change while the process runs

### Requirement: Exactly one worker consumes the intake queue

Strategy Runtime SHALL process the intake queue with exactly one consumer,
and that consumer SHALL be the only caller of
`CommittedBarOrchestrator.process` for events arriving through the
closed-bar webhook.

#### Scenario: Sequential processing
- **WHEN** two or more events are queued
- **THEN** the second event's `CommittedBarOrchestrator.process` call does
  not begin until the first event's call has returned, whether it returned
  normally or raised

#### Scenario: FIFO processing order
- **WHEN** the worker dequeues events
- **THEN** it processes them in the exact order they were enqueued

#### Scenario: No configurable worker count
- **WHEN** Runtime's configuration is inspected
- **THEN** no setting exists that changes the number of intake-queue
  consumer workers away from exactly one

### Requirement: A full queue rejects the request without creating processing work

When the intake queue is at its configured capacity, Strategy Runtime SHALL
reject the triggering HTTP request rather than blocking, dropping silently,
or evicting an already-queued item.

#### Scenario: Full queue produces a fail-closed HTTP response
- **WHEN** a valid, ready webhook request arrives, the intake boundary is
  still accepting, and the underlying queue is already at capacity
- **THEN** the request is rejected with the existing `503`
  `{"status":"not_ready"}` response
- **AND** no event is enqueued for that request
- **AND** `CommittedBarOrchestrator.process` is not invoked for that request
- **AND** Runtime emits one server-side log line for the rejection, reason
  `queue_full`, containing the rejected event's `instrument`, `timeframe`,
  `open_time_ms`, and the configured queue capacity — since the wire
  response reuses the generic `not_ready` envelope, this log is the only
  operator-visible way to distinguish this rejection from the other
  `not_ready`-producing cases

#### Scenario: Rejection does not evict or reorder existing queue contents
- **WHEN** a request is rejected because the queue is full
- **THEN** every event already in the queue remains queued, in its original
  position, unaffected by the rejection

### Requirement: The intake boundary stops accepting new events before shutdown proceeds

Strategy Runtime SHALL provide one explicit, lock-guarded operation
(`stop_accepting()`) that, once called, causes every subsequent
`put_nowait(...)` call to be rejected — distinctly from a capacity
rejection — rather than continuing to accept requests into a queue whose
worker may already be stopping.

#### Scenario: put_nowait and stop_accepting linearize through one shared lock
- **WHEN** a `put_nowait(event)` call and a `stop_accepting()` call occur
  concurrently
- **THEN** exactly one of two outcomes occurs: either `put_nowait`
  acquires the shared lock first and the event is enqueued (subject to the
  normal capacity check), or `stop_accepting` acquires it first and
  `put_nowait` raises `IntakeNotAccepting` without ever reaching the
  underlying queue
- **AND** there is no outcome where an event is enqueued after
  `stop_accepting()` has already completed

#### Scenario: Rejection after stop_accepting is logged distinctly from a capacity rejection
- **WHEN** a webhook request's `put_nowait` call raises
  `IntakeNotAccepting` (because `stop_accepting()` already ran, regardless
  of whether the queue itself had spare capacity)
- **THEN** the request is rejected with the existing `503`
  `{"status":"not_ready"}` response
- **AND** Runtime emits one server-side log line, reason `intake_stopping`
  (distinct from `queue_full`), containing the rejected event's
  `instrument`, `timeframe`, and `open_time_ms`
- **AND** no event is enqueued and `CommittedBarOrchestrator.process` is
  not invoked for that request

#### Scenario: stop_accepting takes effect immediately, independent of in-flight processing
- **WHEN** `stop_accepting()` has been called, whether or not the worker is
  still finishing a `current` event
- **THEN** every new `put_nowait(...)` call is rejected with
  `IntakeNotAccepting` from that point forward, with no delay waiting for
  the in-flight event to finish

### Requirement: One event's processing failure does not stop the worker

The intake worker SHALL isolate a failure while processing one event from
every subsequently queued event.

#### Scenario: Worker continues after one event fails
- **WHEN** `CommittedBarOrchestrator.process` raises for one dequeued event
  (for example, a deployment-catalog or deployment-selection failure)
- **THEN** the worker logs the failure
- **AND** continues dequeuing and processing subsequent events without the
  worker thread terminating

#### Scenario: Per-instance failure isolation inside one event is unaffected
- **WHEN** the worker processes one event whose selected deployments include
  a strategy instance that fails during dispatch
- **THEN** `CommittedBarOrchestrator.process`'s own existing per-unit failure
  isolation applies exactly as it does outside this queue, and the worker
  observes only that call's already-isolated result

### Requirement: The intake queue performs no deduplication

The intake queue SHALL accept and enqueue every valid event exactly as
received, including an event that is a duplicate of one already processed
or still queued.

#### Scenario: Duplicate accepted events are both enqueued
- **WHEN** two valid requests carrying identical `instrument`, `timeframe`,
  and `open_time_ms` are both accepted
- **THEN** both are enqueued
- **AND** the queue introduces no identity check, cache, or database to
  suppress the second one

#### Scenario: Downstream idempotency remains authoritative
- **WHEN** the worker processes a duplicate event
- **THEN** any resulting no-op behavior comes from existing downstream
  reconciliation/state-save idempotency, not from the queue

#### Scenario: A duplicate event may still perform non-mutating downstream work
- **WHEN** the worker processes a duplicate event through the existing,
  unmodified orchestration path
- **THEN** existing non-mutating calls (for example, an ABI open-position
  lookup) may still occur exactly as they would for any other event
- **AND** what is guaranteed absent is the *mutating* outcome: no second
  trade cycle, no duplicate ABI entry-package create/amend/cancel, and no
  duplicate exchange order mutation caused by the identical event — not the
  absence of every downstream call

### Requirement: The worker's start/stop transitions are atomic with respect to event dequeue

Strategy Runtime SHALL make the decision "does this dequeued event start
processing" atomic with respect to a concurrent `stop_once()` call, so that
no event can begin processing after shutdown has already been requested,
and no event that has already begun processing can be abandoned mid-call.

#### Scenario: An event that becomes current before stop_once() is allowed to finish
- **WHEN** the worker has already acquired its lifecycle lock and marked one
  dequeued event as the current in-flight event before a concurrent
  `stop_once()` call acquires the same lock
- **THEN** `stop_once()`'s transition to `STOPPING` waits until that lock is
  available
- **AND** the current event's `CommittedBarOrchestrator.process` call is
  allowed to run to completion, uninterrupted

#### Scenario: An event that has not yet become current when stop_once() wins is discarded
- **WHEN** `stop_once()` acquires the lifecycle lock and transitions to
  `STOPPING` before a concurrently dequeued event acquires that same lock
- **THEN** that event is discarded without ever being passed to
  `CommittedBarOrchestrator.process`
- **AND** the worker's run loop exits without dequeuing any further event

#### Scenario: The lifecycle lock is never held while an event is processing
- **WHEN** `CommittedBarOrchestrator.process(event)` is executing for the
  current event
- **THEN** the worker's lifecycle lock is not held during that call — it is
  released immediately after the current-event decision and before
  `process(...)` is invoked
- **AND** this is what allows a concurrent `stop_once()` call to observe and
  wait on the correct state without deadlocking against the running call

### Requirement: stop_once() has one well-defined outcome per starting state, and only one caller ever joins

Strategy Runtime SHALL define `stop_once()`'s behavior exactly for each of
the worker's four possible states, and SHALL ensure that when multiple
callers invoke `stop_once()` concurrently, only one of them performs the
underlying thread join.

#### Scenario: Called before start
- **WHEN** `stop_once()` is called while the worker's state is
  `NOT_STARTED`
- **THEN** the state transitions directly to `STOPPED`
- **AND** no `thread.join()` (or equivalent) call is made against a thread
  that was never started

#### Scenario: Called while running
- **WHEN** `stop_once()` is called while the worker's state is `RUNNING`
- **THEN** the state transitions to `STOPPING`
- **AND** the calling code waits for the worker thread to exit (an untimed
  join — see the shutdown-bound requirement below)
- **AND** the state transitions to `STOPPED` only after the thread has
  fully exited

#### Scenario: Called after already stopped
- **WHEN** `stop_once()` is called while the worker's state is already
  `STOPPED`
- **THEN** the call returns immediately as a no-op — no exception, no join
  attempt, no state change

#### Scenario: Called concurrently from two callers
- **WHEN** two callers invoke `stop_once()` at approximately the same time
  while the worker is `RUNNING`
- **THEN** exactly one of the two callers performs the transition to
  `STOPPING` and the subsequent thread join
- **AND** the other caller waits and then observes the resulting `STOPPED`
  state without itself performing a join
- **AND** both calls return only after the state is `STOPPED`

### Requirement: Shutdown does not block the FastAPI event loop while waiting for the worker

Strategy Runtime SHALL offload the worker's potentially long, synchronous
`stop_once()` call to a separate thread from the async lifespan shutdown
path, so that waiting for it does not block the event loop from running
other scheduled work.

#### Scenario: Other event-loop work continues while stop_once() waits
- **WHEN** application shutdown calls `stop_once()` via
  `await asyncio.to_thread(intake_worker.stop_once)` while one event is
  still `current` and processing
- **THEN** other coroutines scheduled on the same event loop continue to
  run and make progress during that wait
- **AND** the four outbound HTTP clients remain open (not yet closed) for
  as long as this wait continues

#### Scenario: Client close waits for the offloaded call to complete
- **WHEN** the offloaded `stop_once()` call returns
- **THEN** the four outbound HTTP clients are closed exactly once,
  immediately afterward, and not before

### Requirement: Shutdown's wait for the current event is an accepted tradeoff, not a proven hang-proof guarantee

Strategy Runtime SHALL wait for one already-current committed-bar event to
finish during shutdown rather than interrupting it, and SHALL NOT claim
that this wait is bounded in every case merely because outbound HTTP calls
have finite configured timeouts.

#### Scenario: Network operations inside the current event are bounded
- **WHEN** the current event's processing performs an outbound call to
  Strategy Engine or ABI
- **THEN** that specific call is bounded by its own existing, already
  -configured finite timeout
  (`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`)

#### Scenario: Local operations inside the current event are not given a new deadline
- **WHEN** the current event's processing performs local work — deployment
  -catalog access, acquiring `StrategyInstanceKeyedMutexRegistry`'s
  per-instance lock, in-memory repository reads/writes — or encounters a
  defect that prevents it from returning
- **THEN** this change introduces no new hard deadline, forced
  interruption, or hard shutdown timeout for that work
- **AND** `stop_once()`'s underlying thread join genuinely waits for as
  long as that work takes, with no upper bound imposed by this capability

#### Scenario: This is documented as an accepted tradeoff, not a safety proof
- **WHEN** this capability's shutdown behavior is documented
- **THEN** it is described as a deliberate choice — waiting for the current
  event rather than risking closing shared outbound clients while that
  event might still be using one of them — not as a proof that shutdown is
  guaranteed to complete within any specific time bound

### Requirement: Queue and worker lifecycle is owned once by the composition root

Strategy Runtime SHALL construct the intake queue and its worker exactly
once per process, start the worker exactly once, and stop it exactly once
— via the ordered sequence `stop_accepting()` then `stop_once()` then
outbound-client close — all owned by the same composition lifecycle owner
responsible for the existing outbound HTTP clients.

#### Scenario: Start once
- **WHEN** the production application starts with a ready configuration
- **THEN** exactly one intake queue and exactly one worker thread are
  constructed and started

#### Scenario: Shutdown discards not-yet-current events but waits for the current one
- **WHEN** the application shuts down while one or more events are queued
  but not yet dequeued, or dequeued but not yet marked current
- **THEN** the worker does not start processing any of them — they are
  discarded, not processed and not persisted
- **AND** if one event's `CommittedBarOrchestrator.process` call is already
  running (already marked current) at the moment shutdown begins, that call
  is allowed to finish (successfully or by raising) rather than being
  interrupted or abandoned
- **AND** shutdown does not, in either case, wait for the queue itself to
  drain — only for the one already-current call, if any, to finish

#### Scenario: Outbound HTTP clients close only after the worker has fully stopped
- **WHEN** the application shuts down
- **THEN** the four shared outbound HTTP clients are closed only after the
  offloaded `stop_once()` call has returned — never while the worker thread
  might still be mid-`process(...)` and potentially still using one of them
- **AND** this ordering holds whether or not an event was current at the
  moment shutdown began

### Requirement: The intake queue makes no cross-process guarantee

The bounded committed-bar intake queue SHALL provide only in-process
buffering and SHALL NOT claim multi-worker, multi-replica, or restart
durability.

#### Scenario: Single-process scope
- **WHEN** Live V1 runs with more than one Runtime process or replica
- **THEN** this capability alone does not coordinate or share queue state
  across those processes
- **AND** each process's queue and worker are independent of any other
  process's
