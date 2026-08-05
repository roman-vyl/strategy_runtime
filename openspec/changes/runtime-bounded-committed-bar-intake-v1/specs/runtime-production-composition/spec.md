## MODIFIED Requirements

### Requirement: Production configuration gates ready composition fail-closed
Strategy Runtime SHALL require `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`, and
`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` unconditionally for any `ready=True`
result of `build_application`, and SHALL never return a partially
constructed *ready* production graph. Two distinct failure stages exist:
config loading/parsing (a missing required variable, a timeout string that
cannot parse to `float`, or a queue-capacity string that cannot parse to a
positive `int`) happens before any outbound HTTP client or the intake queue
is constructed; adapter-constructor validation (a malformed/non-absolute/
non-HTTP(S) URL, a non-finite timeout, a zero/negative timeout, or a
zero/negative queue capacity) happens only during client/queue construction,
after zero or more earlier components already exist. Constructing
`AbiExecutionEventOrchestrator` and connecting its callable to
`create_http_app(...)`, and constructing the committed-bar intake queue and
worker and connecting them to `create_http_app(...)`, are all mandatory
steps inside this same fail-closed boundary: a failure at any of these steps
yields `ready=False` exactly as a failure in any earlier step already does.

#### Scenario: Valid configuration constructs a ready graph
- **WHEN** all six variables are present, each base URL is an absolute
  `http`/`https` URL, each timeout is a finite positive number, and the
  queue capacity is a positive integer
- **THEN** `build_application` constructs the complete production graph,
  including `AbiExecutionEventOrchestrator`, its connected first-fill
  callable, and the committed-bar intake queue and worker
- **AND** the resulting application reports `ready=True`

#### Scenario: A missing or unparsable field fails closed before any client exists
- **WHEN** any of the six variables is missing, or a timeout or queue
  -capacity variable cannot be parsed as its expected numeric type
- **THEN** `build_application` constructs zero outbound HTTP clients, does
  not construct `AbiExecutionEventOrchestrator`, and does not construct the
  intake queue or worker
- **AND** the resulting application reports `ready=False`, matching the
  existing not-ready pattern already used for invalid `RuntimeConfig`

#### Scenario: A first-fill wiring failure still fails closed
- **WHEN** constructing `AbiExecutionEventOrchestrator` or connecting its
  callable to `create_http_app(...)` fails, after zero or more outbound
  HTTP clients already constructed successfully
- **THEN** the composition lifecycle owner closes every outbound HTTP
  client already constructed, exactly once each, as part of startup
  rollback — before `build_application` returns the not-ready application
- **AND** `build_application` returns a not-ready application instead of a
  partially constructed production graph
- **AND** no partially wired, `ready=True` application with a `None` or
  disconnected first-fill callable is ever returned

#### Scenario: An intake-queue wiring failure still fails closed
- **WHEN** constructing the committed-bar intake queue or worker, or
  connecting the queue to `create_http_app(...)`, fails after zero or more
  earlier components already constructed successfully
- **THEN** the composition lifecycle owner closes or stops every component
  already constructed, exactly once each, as part of startup rollback —
  before `build_application` returns the not-ready application
- **AND** `build_application` returns a not-ready application instead of a
  partially constructed production graph
- **AND** no partially wired, `ready=True` application with a `None` intake
  queue or an unstarted worker is ever returned

#### Scenario: A later construction-time rejection still fails closed
- **WHEN** one or more earlier outbound HTTP clients or the intake queue, in
  the deterministic construction order, already constructed successfully,
  and a later component's constructor rejects a successfully parsed but
  semantically invalid field (non-`http`/`https` URL, `NaN`/infinite
  timeout, zero/negative timeout, or zero/negative queue capacity)
- **THEN** `build_application` closes or stops every component already
  constructed before that rejection, via startup rollback
- **AND** the resulting application reports `ready=False`
- **AND** no partially usable production graph is ever returned as
  `ready=True`

#### Scenario: One ABI base URL serves two independently timed-out adapters
- **WHEN** the production graph is constructed
- **THEN** `HttpxAbiOpenPositionLookupAdapter` and the existing
  `HttpxAbiEntryPackageAdapter` are both constructed from the same
  `RUNTIME_ABI_BASE_URL`
- **AND** each uses its own distinct timeout
  (`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS` and
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`, respectively)

#### Scenario: No speculative reliability configuration is added
- **WHEN** the configuration fields are validated
- **THEN** no retry-count, circuit-breaker, or other speculative reliability
  policy field is introduced
- **AND** no worker-count configuration field is introduced for the intake
  queue — its consumer count is fixed at exactly one and is not
  configurable

### Requirement: Non-durable Live V1 limitation is accepted, not open
Strategy Runtime SHALL use exactly one
`InMemoryStrategyInstanceRuntimeStateRepository` for `I4d`'s production
graph and exactly one bounded, in-memory, non-persisted committed-bar
intake queue, and SHALL treat the resulting non-durable behavior of both as
an accepted Live V1 limitation rather than an unresolved task of this
change.

#### Scenario: In-memory repository is the selected implementation
- **WHEN** the production graph is constructed
- **THEN** the shared state repository is
  `InMemoryStrategyInstanceRuntimeStateRepository`
- **AND** `infrastructure/runtime_state/sqlite_repository.py` remains an
  unimplemented placeholder, not a partially completed component of this
  change

#### Scenario: A lost in-flight cycle is an accepted risk
- **WHEN** Runtime terminates after acknowledging a webhook but before its
  queued committed-bar cycle completes
- **THEN** that in-flight cycle is lost with no persisted pending action,
  replay, or recovery mechanism
- **AND** this is documented as an accepted Live V1 limitation, matching the
  existing single-process, single-worker, non-durable concurrency model

#### Scenario: A queued-but-undequeued event is an equally accepted risk
- **WHEN** Runtime terminates after accepting a webhook and enqueuing its
  event, but before the intake worker dequeues it
- **THEN** that event is lost with no persistence, replay, or recovery
  mechanism, exactly like an in-flight cycle already lost after dequeue
- **AND** no transactional outbox, durable queue, or event log is
  introduced to close this gap in Live V1

## ADDED Requirements

### Requirement: Runtime composes exactly one committed-bar intake queue and its single worker
`strategy_runtime.bootstrap.application.build_application` SHALL construct,
for every `ready=True` result, exactly one bounded committed-bar intake
queue and exactly one `CommittedBarIntakeWorker`, and SHALL connect the
worker to the same, already-constructed `CommittedBarOrchestrator` instance
used by the rest of the production graph — introducing no second
orchestrator instance.

#### Scenario: One queue, one worker, wired to the existing orchestrator
- **WHEN** `build_application` constructs a ready application
- **THEN** exactly one intake queue object and exactly one
  `CommittedBarIntakeWorker` object are created
- **AND** the worker calls `process(...)` on the same
  `CommittedBarOrchestrator` instance already constructed for this
  application, not a separately constructed one

#### Scenario: The webhook handler and the worker share the same queue object
- **WHEN** the production graph is constructed
- **THEN** the exact queue object the closed-bar webhook handler enqueues
  into is the exact queue object the worker consumes from
- **AND** `create_http_app(...)` receives that same queue object as its
  committed-bar intake parameter

### Requirement: Committed-bar intake worker is started once and stopped exactly once by one lifecycle owner
The composition root SHALL be the single owner of the committed-bar intake
worker's start/stop lifecycle, matching the existing ownership pattern
already established for the four outbound HTTP clients.

#### Scenario: Started during application startup
- **WHEN** the production application's lifespan begins
- **THEN** the intake worker is started exactly once, before the
  application begins accepting requests that could enqueue into it in a
  way that races its own startup

#### Scenario: Stopped during application shutdown, by the same owner
- **WHEN** the production application shuts down
- **THEN** the same lifecycle owner responsible for closing the four
  outbound HTTP clients also stops the intake worker, exactly once
- **AND** no HTTP request handler, background thread, or orchestrator call
  ever stops the worker itself

#### Scenario: Worker stop happens strictly before outbound client close
- **WHEN** the production application shuts down
- **THEN** the lifecycle owner stops the intake worker — waiting for it to
  fully exit, including letting any currently in-flight
  `CommittedBarOrchestrator.process(...)` call finish rather than
  interrupting it — strictly before closing any of the four outbound HTTP
  clients
- **AND** this ordering holds even though the worker's own shutdown wait is
  not bounded by a fixed timeout of its own, but by the finite outbound
  timeouts already enforced inside that in-flight call
