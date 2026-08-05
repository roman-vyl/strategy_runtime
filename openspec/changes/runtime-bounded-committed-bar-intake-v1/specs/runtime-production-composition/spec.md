## MODIFIED Requirements

### Requirement: Production configuration gates ready composition fail-closed
Strategy Runtime SHALL require `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`, and
`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` unconditionally for any
`ready=True` result of `build_application`, and SHALL never return a
partially constructed *ready* production graph. Constructing
`AbiExecutionEventOrchestrator` and the committed-bar intake queue/worker,
and connecting both to `create_http_app(...)`, are mandatory steps inside
the same fail-closed boundary as every earlier component.

#### Scenario: Valid configuration constructs a ready graph
- **WHEN** all six variables are present and valid (absolute `http`/
  `https` URLs, finite positive timeouts, a positive integer queue
  capacity)
- **THEN** `build_application` constructs the complete production graph,
  including `AbiExecutionEventOrchestrator` and the committed-bar intake
  queue and worker, and reports `ready=True`

#### Scenario: A missing, unparsable, or later-rejected field fails closed
- **WHEN** any required variable is missing or unparsable, or a later
  component's constructor rejects a successfully parsed but semantically
  invalid field (non-`http`/`https` URL, non-finite or non-positive
  timeout, non-positive queue capacity)
- **THEN** `build_application` closes or stops every component already
  constructed, exactly once each, via startup rollback, and reports
  `ready=False` — no partially wired `ready=True` application, with a
  disconnected first-fill callable, a `None` intake boundary, or an
  unstarted worker, is ever returned

#### Scenario: No speculative reliability configuration is added
- **WHEN** the configuration fields are validated
- **THEN** no retry-count, circuit-breaker, or other speculative
  reliability field is introduced, and no worker-count field is
  introduced for the intake queue

### Requirement: Non-durable Live V1 limitation is accepted, not open
Strategy Runtime SHALL use exactly one
`InMemoryStrategyInstanceRuntimeStateRepository` and exactly one bounded,
in-memory, non-persisted committed-bar intake queue for `I4d`'s
production graph, and SHALL treat the resulting non-durable behavior of
both as an accepted Live V1 limitation.

#### Scenario: In-flight and queued-but-undequeued events are an accepted risk
- **WHEN** Runtime terminates after acknowledging a webhook but before
  its queued committed-bar cycle completes, whether or not the worker
  had already dequeued it
- **THEN** that event is lost with no persisted pending action, replay,
  or recovery mechanism, and this is documented as an accepted Live V1
  limitation rather than an unresolved task of this change

## ADDED Requirements

### Requirement: Runtime composes exactly one committed-bar intake boundary and its single worker
`build_application` SHALL construct, for every `ready=True` result,
exactly one `CommittedBarIntakeBoundary` and exactly one
`CommittedBarIntakeWorker`, and SHALL connect the worker to the same,
already-constructed `CommittedBarOrchestrator` instance used by the rest
of the production graph — introducing no second orchestrator instance.

#### Scenario: One boundary, one worker, shared with the webhook handler
- **WHEN** `build_application` constructs a ready application
- **THEN** exactly one `CommittedBarIntakeBoundary` and exactly one
  `CommittedBarIntakeWorker` are created, the worker calls `process(...)`
  on the same `CommittedBarOrchestrator` instance already constructed
  for this application, and the closed-bar webhook handler and the
  worker share that exact boundary object — `create_http_app(...)` never
  receives the underlying queue directly

### Requirement: Committed-bar intake worker is started once and stopped exactly once by one lifecycle owner, in a fixed shutdown sequence
The composition root SHALL be the single owner of the worker's start/stop
lifecycle, matching the existing ownership pattern for the four outbound
HTTP clients, and SHALL execute shutdown as three ordered steps: stop
accepting new events, then wait for the worker to stop, then close the
outbound HTTP clients.

#### Scenario: Started once at startup, stopped once at shutdown by the same owner
- **WHEN** the production application's lifespan begins
- **THEN** the intake worker is started exactly once, before the
  application begins accepting requests
- **AND** when the application shuts down, that same lifecycle owner —
  never an HTTP request handler, background thread, or orchestrator call
  — stops the worker exactly once

#### Scenario: Stop-accepting first, then an event-loop-safe wait, then client close
- **WHEN** the production application shuts down
- **THEN** the lifecycle owner first calls `stop_accepting()`
  synchronously on the event-loop thread (a single lock acquisition that
  never blocks), then waits for the worker to stop via `await asyncio
  .to_thread(intake_worker.stop_once)` — so other coroutines on the same
  event loop keep running during that wait — and only closes the four
  outbound HTTP clients after that offloaded call returns
- **AND** this ordering holds regardless of how long the wait takes: its
  network operations are bounded by existing outbound timeouts, but its
  local operations are not bounded by any timeout this change introduces
