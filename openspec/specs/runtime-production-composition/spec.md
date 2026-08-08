# runtime-production-composition Specification

## Purpose
Define the production composition of the complete strategy runtime application graph, including the utility contour, semantic core, and all outbound HTTP adapters, with configuration requirements and lifecycle ownership.
## Requirements
### Requirement: Runtime composes exactly one complete production graph
`strategy_runtime.bootstrap.application.build_application` SHALL construct,
for every `ready=True` result, the complete production graph from the
existing utility contour through the existing semantic core and existing
outbound adapters to the existing `AbiEntryPackagePort` and
`PositionManagementExecutionPort` HTTP clients, using only components
already implemented and tested in isolation by prior changes, and SHALL
additionally construct exactly one `AbiExecutionEventOrchestrator` and
connect it to `create_http_app(...)` as the first-fill application
callable. `StrategyRuntimeOrchestrator`'s constructor is the one component
this change itself extends, to accept `position_management_orchestrator`;
every other component in the graph is consumed exactly as already
implemented, with no redesign. There is no caller-supplied override that
replaces any part of this graph, and no construction path returns
`ready=True` with only part of it.

#### Scenario: Compose the existing components, not new ones
- **WHEN** `build_application` constructs a ready application
- **THEN** it constructs `OpenPositionResolver`, `StrategyUseCaseRouter`,
  `EntryReconciliationOrchestrator`, `PositionManagementOrchestrator`, and
  `AbiExecutionEventOrchestrator` from their existing, unmodified
  constructors, and constructs `StrategyRuntimeOrchestrator` from its
  constructor as extended by this change to additionally accept
  `position_management_orchestrator`
- **AND** it constructs `HttpxStrategyEngineLiveEntryAdapter`,
  `HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
  `HttpxAbiEntryPackageAdapter`, and `HttpxAbiPositionManagementAdapter`
  from their existing, unmodified constructors
- **AND** `PositionManagementOrchestrator` and
  `HttpxAbiPositionManagementAdapter` are consumed exactly as already
  ratified, with no redesign of either
- **AND** it introduces no new top-level orchestrator, reconciliation
  component, or outbound adapter class beyond the already-shipped
  `AbiExecutionEventOrchestrator` and `PositionManagementOrchestrator`
- **AND** it introduces no new outbound HTTP client beyond the
  already-shipped `HttpxAbiPositionManagementAdapter`

#### Scenario: Attach the semantic core through a thin production sink, unconditionally
- **WHEN** `build_application` constructs a ready application
- **THEN** `StrategyCycleHandoffBoundary` is constructed with a thin,
  `None`-returning sink function that calls
  `StrategyRuntimeOrchestrator.process(unit)` and discards its result
- **AND** no unattached (no-op) sink is used, and no other sink is ever
  attached in a `ready=True` application
- **AND** `.dispatch` is not used as the sink (it would construct a second,
  discarded `StrategyCycleDispatchOutcome`)

#### Scenario: Connect a thin first-fill callable to create_http_app
- **WHEN** `build_application` constructs a ready application
- **THEN** it constructs a thin callable that calls
  `AbiExecutionEventOrchestrator.process(event)` and returns its result
  unmodified
- **AND** it passes that callable into `create_http_app(...)` as the
  application's first-fill use case
- **AND** the ready application's FastAPI instance has a connected,
  non-`None` first-fill callable

#### Scenario: A not-ready application never executes the first-fill use case
- **WHEN** `build_application` returns a `ready=False` application, whether
  from a configuration failure or a construction failure at any stage
- **THEN** the returned application's first-fill callable is `None`
- **AND** `AbiExecutionEventOrchestrator.process(...)` is never invoked
  through the not-ready application's HTTP surface

#### Scenario: No caller-supplied composition override exists
- **WHEN** `build_application`'s public signature is inspected
- **THEN** it accepts no `strategy_cycle_handoff`, no first-fill callable
  override, and no equivalent parameter that could replace the production
  sink, replace the production first-fill callable, skip constructing the
  semantic graph, skip constructing `AbiExecutionEventOrchestrator`, or
  skip constructing any of the five outbound HTTP clients
- **AND** every `ready=True` application it returns has the complete graph
  constructed — there is no alternative utility-only `ready=True` result

### Requirement: Exactly one shared state repository and keyed-mutex registry
`build_application` SHALL construct exactly one
`StrategyInstanceRuntimeStateRepository` instance and exactly one
`StrategyInstanceKeyedMutexRegistry` instance per application, and SHALL
pass the same two instances into both the one constructed
`StrategyRuntimeOrchestrator` and the one constructed
`AbiExecutionEventOrchestrator`.

#### Scenario: Single repository instance
- **WHEN** the production graph is constructed
- **THEN** exactly one `InMemoryStrategyInstanceRuntimeStateRepository`
  object is created
- **AND** that exact object is the one `StrategyRuntimeOrchestrator` uses
  for every background cycle across every strategy instance
- **AND** that same exact object is the one `AbiExecutionEventOrchestrator`
  uses for every first-fill event across every strategy instance

#### Scenario: Single keyed-mutex-registry instance
- **WHEN** the production graph is constructed
- **THEN** exactly one `StrategyInstanceKeyedMutexRegistry` object is
  created
- **AND** that exact object is the one `StrategyRuntimeOrchestrator` uses
  to serialize every strategy instance's closed-bar critical section
- **AND** that same exact object is the one `AbiExecutionEventOrchestrator`
  uses to serialize every strategy instance's first-fill critical section

#### Scenario: Shared between both existing top-level writers, with no alternative build mode
- **WHEN** the composition root finishes construction
- **THEN** the constructed repository and keyed-mutex-registry instances
  are the same two objects held by both existing top-level writers —
  `StrategyRuntimeOrchestrator` (the closed-bar writer) and
  `AbiExecutionEventOrchestrator` (the first-fill writer)
- **AND** both instances remain reachable from the composition-owned
  `app.state` that `build_application` returns, for test and operational
  access (not only closed over privately and unreachably inside either
  orchestrator)
- **AND** no alternative build mode, parameter, or flag exists to obtain
  either instance, or to construct either writer with a different pair of
  instances, outside this one construction path

#### Scenario: AbiExecutionEventOrchestrator is constructed exactly once, over the shared instances
- **WHEN** the production graph is constructed
- **THEN** exactly one `AbiExecutionEventOrchestrator` object is created
- **AND** it is constructed with `state_repository` and
  `keyed_mutex_registry` set to the exact same objects passed into
  `StrategyRuntimeOrchestrator`
- **AND** no second `StrategyInstanceRuntimeStateRepository` or
  `StrategyInstanceKeyedMutexRegistry` object is created for
  `AbiExecutionEventOrchestrator`'s own use

### Requirement: Outbound HTTP clients are constructed once and closed exactly once by one lifecycle owner
The composition root SHALL be the single owner of the five production HTTP
clients (`HttpxStrategyEngineLiveEntryAdapter`,
`HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
`HttpxAbiEntryPackageAdapter`, `HttpxAbiPositionManagementAdapter`): each
SHALL be constructed exactly once during `build_application`, reused across
every background committed-bar cycle for the application's life, and closed
exactly once by that same lifecycle owner — either during startup rollback
(if construction fails partway) or during application shutdown (if
construction succeeded) — and never by any other caller.

#### Scenario: Construct once, reuse across cycles
- **WHEN** the composed application processes multiple committed-bar cycles,
  across one or many strategy instances
- **THEN** the same five HTTP client instances handle every outbound call
- **AND** no HTTP client is constructed per request or per background cycle

#### Scenario: Close every owned client exactly once on shutdown
- **WHEN** the application shuts down after a successful ready construction
- **THEN** each of the five owned HTTP clients is closed exactly once, by the
  composition lifecycle owner
- **AND** no owned client is left open

#### Scenario: Startup rollback closes what was built, not shutdown
- **WHEN** constructing the five HTTP clients fails partway (a later
  client's configuration is rejected after one or more earlier clients
  constructed successfully)
- **THEN** the composition lifecycle owner closes every client already
  constructed, exactly once each, as part of startup rollback — before
  `build_application` returns the not-ready application
- **AND** `build_application` returns a not-ready application instead of a
  partially constructed production graph
- **AND** those rolled-back clients are not exposed in any returned
  application and are not closed again later

#### Scenario: Only the composition lifecycle owner ever closes a client
- **WHEN** a background cycle, an HTTP request, or an individual outbound
  adapter call completes, whether successfully or with a failure
- **THEN** none of an HTTP request handler, a background committed-bar cycle,
  `StrategyRuntimeOrchestrator`, `OpenPositionResolver`,
  `StrategyUseCaseRouter`, `EntryReconciliationOrchestrator`,
  `PositionManagementOrchestrator`, an outbound adapter itself, or any other
  caller calls `close()` on any of the five owned clients
- **AND** only the composition lifecycle owner calls `close()`, and only
  during startup rollback or application shutdown

### Requirement: Production configuration gates ready composition fail-closed
Strategy Runtime SHALL require `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`,
`RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS`, and
`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` unconditionally for any
`ready=True` result of `build_application`, and SHALL never return a
partially constructed *ready* production graph. Constructing
`AbiExecutionEventOrchestrator` and the committed-bar intake queue/worker,
and connecting both to `create_http_app(...)`, are mandatory steps inside
the same fail-closed boundary as every earlier component.

#### Scenario: Valid configuration constructs a ready graph
- **WHEN** all seven variables are present and valid (absolute `http`/
  `https` URLs, finite positive timeouts, a positive integer queue
  capacity)
- **THEN** `build_application` constructs the complete production graph,
  including `AbiExecutionEventOrchestrator` and the committed-bar intake
  queue and worker, and reports `ready=True`

#### Scenario: A missing or unparsable field fails closed before any client exists
- **WHEN** any required variable is missing or unparsable
- **THEN** `build_application` constructs zero outbound HTTP clients and
  does not construct `AbiExecutionEventOrchestrator` or the intake
  boundary/worker, and reports `ready=False`

#### Scenario: A first-fill wiring failure still fails closed
- **WHEN** constructing `AbiExecutionEventOrchestrator`, the intake
  boundary/worker, or connecting either to `create_http_app(...)` fails,
  after zero or more earlier components already constructed successfully
- **THEN** `build_application` closes or stops every component already
  constructed, exactly once each, via startup rollback, and reports
  `ready=False` — no partially wired `ready=True` application, with a
  disconnected first-fill callable, a `None` intake boundary, or an
  unstarted worker, is ever returned

#### Scenario: A later construction-time rejection still fails closed
- **WHEN** a later component's constructor rejects a successfully parsed
  but semantically invalid field (non-`http`/`https` URL, non-finite or
  non-positive timeout, non-positive queue capacity), after one or more
  earlier components already constructed successfully
- **THEN** `build_application` closes every component already constructed
  before that rejection, via startup rollback, and reports `ready=False`

#### Scenario: One ABI base URL serves three independently timed-out adapters
- **WHEN** the production graph is constructed
- **THEN** `HttpxAbiOpenPositionLookupAdapter`, `HttpxAbiEntryPackageAdapter`,
  and `HttpxAbiPositionManagementAdapter` are all constructed from the same
  `RUNTIME_ABI_BASE_URL`, each using its own distinct timeout
  (`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`, and
  `RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS`, respectively)

#### Scenario: No speculative reliability configuration is added
- **WHEN** the configuration fields are validated
- **THEN** no retry-count, circuit-breaker, or other speculative
  reliability field is introduced, and no worker-count field is
  introduced for the intake queue

### Requirement: Two acknowledgement boundaries remain distinct
Strategy Runtime SHALL treat the MDS webhook acknowledgement and any ABI
execution acknowledgement (entry-package, protection, or close) as two
independent confirmation boundaries, and SHALL NOT let a downstream outcome
change the already-sent HTTP response or let the HTTP acknowledgement
authorize any state mutation.

#### Scenario: HTTP acknowledgement authorizes nothing beyond acceptance
- **WHEN** Runtime returns `200 {"status":"accepted"}` for a valid, ready
  webhook request
- **THEN** that response does not assert that Strategy Engine projected
  successfully, that ABI acknowledged an entry package or a
  protection/close request, that Runtime state was saved, or that an
  exchange order was placed, amended, or filled

#### Scenario: Only ABI acknowledgement authorizes entry-reconciliation state application
- **WHEN** `EntryReconciliationOrchestrator` holds a command-bearing decision
  (`Apply`, `Replace`, or `Cancel`)
- **THEN** it applies the reconciliation result and allows
  `StrategyRuntimeOrchestrator` to save replacement state only after receiving
  `EntryAppliedConfirmation` or `EntryAbsentConfirmation` from the entry
  -execution bridge
- **AND** no unconfirmed outcome from Strategy Engine, ABI open-position
  lookup, or ABI entry-package produces a save

#### Scenario: Only ABI acknowledgement authorizes position-management state application
- **WHEN** `PositionManagementOrchestrator` holds a command-bearing decision
  (`ApplyProtection` or `ClosePosition`)
- **THEN** it applies the decision and allows `StrategyRuntimeOrchestrator`
  to save replacement state only after receiving a verified
  `ProtectionAppliedConfirmation` or `PositionClosedConfirmation` from
  `PositionManagementExecutionPort`
- **AND** no unconfirmed outcome from ABI protection or close produces a
  save

#### Scenario: Downstream failure is recorded, not surfaced over HTTP
- **WHEN** any outbound call inside the background critical section fails
  after the HTTP acknowledgement was already sent
- **THEN** the already-sent HTTP response is not changed or repeated
- **AND** the failure is recorded through the existing processing-journal/
  outcome mechanism
- **AND** no fabricated success, no false `position_open=false`, and no
  unconfirmed `CurrentTradeCycle` save results from that failure

### Requirement: Non-durable Live V1 limitation is accepted, not open
Strategy Runtime SHALL use exactly one
`InMemoryStrategyInstanceRuntimeStateRepository` and exactly one bounded,
in-memory, non-persisted committed-bar intake queue for `I4d`'s
production graph, and SHALL treat the resulting non-durable behavior of
both as an accepted Live V1 limitation.

#### Scenario: In-memory repository is the selected implementation
- **WHEN** the production graph is constructed
- **THEN** the shared state repository is
  `InMemoryStrategyInstanceRuntimeStateRepository`
- **AND** no durable repository implementation is composed for Live V1

#### Scenario: A lost in-flight cycle is an accepted risk
- **WHEN** Runtime terminates after acknowledging a webhook but before
  its queued committed-bar cycle completes, whether or not the worker
  had already dequeued it from the intake queue
- **THEN** that event is lost with no persisted pending action, replay,
  or recovery mechanism, and this is documented as an accepted Live V1
  limitation rather than an unresolved task of this change

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
lifecycle, matching the existing ownership pattern for the five outbound
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
  event loop keep running during that wait — and only closes the five
  outbound HTTP clients after that offloaded call returns
- **AND** this ordering holds regardless of how long the wait takes: its
  network operations are bounded by existing outbound timeouts, but its
  local operations are not bounded by any timeout this change introduces
