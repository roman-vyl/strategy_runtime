## ADDED Requirements

### Requirement: Runtime bounds accepted committed-bar events in one FIFO queue

Strategy Runtime SHALL hold accepted `CommittedBarEvent`s in exactly one
bounded, process-local, first-in-first-out queue between HTTP acceptance and
semantic processing.

#### Scenario: Accepted events enter the queue in order
- **WHEN** the closed-bar webhook accepts two or more valid requests while
  Runtime is ready and the queue has capacity
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
- **WHEN** a valid, ready webhook request arrives and the intake queue is
  already at capacity
- **THEN** the request is rejected with the existing `503`
  `{"status":"not_ready"}` response
- **AND** no event is enqueued for that request
- **AND** `CommittedBarOrchestrator.process` is not invoked for that request

#### Scenario: Rejection does not evict or reorder existing queue contents
- **WHEN** a request is rejected because the queue is full
- **THEN** every event already in the queue remains queued, in its original
  position, unaffected by the rejection

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

### Requirement: Queue and worker lifecycle is owned once by the composition root

Strategy Runtime SHALL construct the intake queue and its worker exactly
once per process, start the worker exactly once, and stop it exactly once,
all owned by the same composition lifecycle owner responsible for the
existing outbound HTTP clients.

#### Scenario: Start once
- **WHEN** the production application starts with a ready configuration
- **THEN** exactly one intake queue and exactly one worker thread are
  constructed and started

#### Scenario: Stop once, without hanging
- **WHEN** the application shuts down
- **THEN** the worker stops within a bounded time budget
- **AND** shutdown does not wait for the queue to drain
- **AND** any event still queued at shutdown is discarded, not processed
  and not persisted

#### Scenario: A second stop is a no-op
- **WHEN** the lifecycle owner's stop path runs more than once (for example,
  once during startup rollback and once during normal shutdown, or two
  overlapping shutdown signals)
- **THEN** the second and any later stop call does not raise and does not
  attempt to join an already-joined thread a second time

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
