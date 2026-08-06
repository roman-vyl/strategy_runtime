## ADDED Requirements

### Requirement: Runtime bounds accepted committed-bar events in one FIFO queue
Strategy Runtime SHALL hold accepted `CommittedBarEvent`s in exactly one
bounded, process-local, first-in-first-out queue between HTTP acceptance
and semantic processing, owned by one `CommittedBarIntakeBoundary` object
— no caller outside that object holds a reference to the underlying queue
directly.

#### Scenario: Accepted events enter and leave the queue in order
- **WHEN** the closed-bar webhook accepts two or more valid requests
  while Runtime is ready, the boundary is still accepting, and the queue
  has capacity
- **THEN** each accepted event is enqueued in the order its request was
  accepted, and the worker dequeues them in that same order

#### Scenario: The queue has a fixed, configured capacity
- **WHEN** Runtime starts with a ready configuration
- **THEN** the intake queue's maximum size equals the validated
  `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` value, and that capacity does not
  change while the process runs

### Requirement: Exactly one worker consumes the intake queue
Strategy Runtime SHALL process the intake queue with exactly one
consumer, which SHALL be the only caller of `CommittedBarOrchestrator
.process` for events arriving through the closed-bar webhook, and no
configuration SHALL change that count.

#### Scenario: Sequential processing
- **WHEN** two or more events are queued
- **THEN** the second event's `CommittedBarOrchestrator.process` call
  does not begin until the first has returned, whether it returned
  normally or raised

#### Scenario: No configurable worker count
- **WHEN** Runtime's configuration is inspected
- **THEN** no setting exists that changes the number of intake-queue
  consumer workers away from exactly one

### Requirement: A full queue rejects the request without creating processing work
When the intake queue is at its configured capacity, Strategy Runtime
SHALL reject the triggering HTTP request rather than blocking, dropping
silently, or evicting an already-queued item.

#### Scenario: Full queue produces a fail-closed response and no work
- **WHEN** a valid, ready webhook request arrives, the boundary is still
  accepting, and the queue is already at capacity
- **THEN** the request is rejected (see `http-closed-bar`), no event is
  enqueued for it, `CommittedBarOrchestrator.process` is not invoked, and
  every event already queued remains queued, in its original position

### Requirement: The intake boundary stops accepting new events before shutdown proceeds
Strategy Runtime SHALL provide one explicit, lock-guarded operation,
`stop_accepting()`, that once called causes every subsequent
`put_nowait` call to be rejected — distinctly from a capacity rejection —
with no delay waiting for any in-flight event to finish.

#### Scenario: put_nowait and stop_accepting linearize through one shared lock
- **WHEN** a `put_nowait(event)` call and a `stop_accepting()` call occur
  concurrently
- **THEN** exactly one of two outcomes occurs: `put_nowait` acquires the
  shared lock first and the event is enqueued (subject to the normal
  capacity check), or `stop_accepting` acquires it first and `put_nowait`
  raises `IntakeNotAccepting` without ever reaching the underlying queue
- **AND** there is no outcome where an event is enqueued after
  `stop_accepting()` has already completed

#### Scenario: Rejection after stop_accepting is logged distinctly
- **WHEN** a webhook request's `put_nowait` call raises
  `IntakeNotAccepting`
- **THEN** the request is rejected (see `http-closed-bar`) and Runtime
  emits one server-side log line, reason `intake_stopping`, distinct
  from `queue_full`

### Requirement: One event's processing failure does not stop the worker
The intake worker SHALL isolate a failure while processing one event from
every subsequently queued event, without affecting
`CommittedBarOrchestrator.process`'s own existing per-instance failure
isolation.

#### Scenario: Worker continues after one event fails
- **WHEN** `CommittedBarOrchestrator.process` raises for one dequeued
  event
- **THEN** the worker logs the failure and continues dequeuing and
  processing subsequent events without the worker thread terminating

### Requirement: The intake queue performs no deduplication
The intake queue SHALL accept and enqueue every valid event exactly as
received, including a duplicate of one already processed or still
queued, relying on existing downstream idempotency rather than
introducing a new dedup mechanism.

#### Scenario: Duplicates are enqueued and processed like any other event
- **WHEN** two valid requests carrying identical `instrument`,
  `timeframe`, and `open_time_ms` are both accepted
- **THEN** both are enqueued and processed through the same, unmodified
  orchestration path, with no identity check, cache, or database at the
  queue boundary to suppress the second one

#### Scenario: Downstream idempotency is authoritative for the outcome
- **WHEN** the worker processes a duplicate event
- **THEN** any resulting no-op behavior comes from existing downstream
  reconciliation/state-save idempotency, not from the queue — a
  duplicate may still perform an existing non-mutating call (for
  example, an ABI open-position lookup), but produces no second trade
  cycle, no duplicate entry-package create/amend/cancel, and no
  duplicate exchange mutation

### Requirement: The worker's lifecycle is one atomic, race-free state machine
Strategy Runtime SHALL drive the worker through exactly four states —
not_started, running, stopping, stopped — and SHALL make every
transition atomic with respect to concurrent callers: the decision that a
dequeued event becomes current is atomic with respect to a concurrent
`stop_once()` call, `start()` cannot be observed as running before the
underlying thread has actually started, and only one concurrent
`stop_once()` caller ever performs the underlying thread join.

#### Scenario: An event already current when stop_once() runs is finished, not abandoned
- **WHEN** the worker has already marked one dequeued event as current
  before a concurrent `stop_once()` call is invoked
- **THEN** `stop_once()` waits until that event's `CommittedBarOrchestrator
  .process` call has run to completion before transitioning to stopped

#### Scenario: An event not yet current when stop_once() wins is discarded
- **WHEN** `stop_once()` transitions to stopping before a concurrently
  dequeued event becomes current
- **THEN** that event is discarded without ever being passed to
  `CommittedBarOrchestrator.process`, and the worker's run loop exits
  without dequeuing any further event

#### Scenario: stop_once() is idempotent and only one caller ever joins
- **WHEN** `stop_once()` is called before `start()`, after the worker is
  already stopped, or concurrently by two callers while running
- **THEN** calling it before `start()` or after already stopped is a
  no-op that never attempts a thread join, and calling it concurrently
  from two callers results in exactly one of them performing the join
  while the other waits and then observes stopped

#### Scenario: start() cannot race a concurrent stop_once()
- **WHEN** `start()` and a concurrent `stop_once()` are both invoked
- **THEN** `stop_once()` cannot observe the worker as running until the
  underlying thread has actually started, so it never attempts to join a
  thread that was never started

### Requirement: The intake queue makes no cross-process guarantee
The bounded committed-bar intake queue SHALL provide only in-process
buffering and SHALL NOT claim multi-worker, multi-replica, or restart
durability.

#### Scenario: Single-process scope
- **WHEN** Live V1 runs with more than one Runtime process or replica
- **THEN** this capability does not coordinate or share queue state
  across those processes — each process's queue and worker are
  independent
