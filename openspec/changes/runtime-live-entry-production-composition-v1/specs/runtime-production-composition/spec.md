## ADDED Requirements

### Requirement: Runtime composes exactly one production live-entry graph
`strategy_runtime.bootstrap.application.build_application` SHALL construct, for
a ready application, the complete production graph from the existing utility
contour through the existing semantic core and existing outbound adapters to
the existing `AbiEntryPackagePort` HTTP client, using only components already
implemented and tested in isolation by prior changes.

#### Scenario: Compose the existing components, not new ones
- **WHEN** `build_application` constructs a ready application
- **THEN** it constructs `OpenPositionResolver`, `StrategyUseCaseRouter`,
  `EntryReconciliationOrchestrator`, and `StrategyRuntimeOrchestrator` from
  their existing, unmodified constructors
- **AND** it constructs `HttpxStrategyEngineLiveEntryAdapter`,
  `HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
  and the existing `HttpxAbiEntryPackageAdapter` from their existing,
  unmodified constructors
- **AND** it introduces no new top-level orchestrator, reconciliation
  component, or outbound adapter class

#### Scenario: Attach the semantic core through a thin production sink
- **WHEN** `build_application` is called without a caller-supplied
  `strategy_cycle_handoff` override
- **THEN** `StrategyCycleHandoffBoundary` is constructed with a thin,
  `None`-returning sink function that calls
  `StrategyRuntimeOrchestrator.process(unit)` and discards its result
- **AND** no unattached (no-op) sink is used in that default production path
- **AND** `.dispatch` is not used as the sink (it would construct a second,
  discarded `StrategyCycleDispatchOutcome`)

#### Scenario: Preserve the existing test override seam
- **WHEN** a caller supplies an explicit `strategy_cycle_handoff` argument to
  `build_application`
- **THEN** that caller-supplied sink is used instead of the production
  `StrategyRuntimeOrchestrator` sink
- **AND** this override seam remains available for tests only, never as a
  documented production configuration path

### Requirement: Exactly one shared state repository and keyed-mutex registry
`build_application` SHALL construct exactly one
`StrategyInstanceRuntimeStateRepository` instance and exactly one
`StrategyInstanceKeyedMutexRegistry` instance per application, and SHALL pass
the same two instances into the one constructed `StrategyRuntimeOrchestrator`.

#### Scenario: Single repository instance
- **WHEN** the production graph is constructed
- **THEN** exactly one `InMemoryStrategyInstanceRuntimeStateRepository` object
  is created
- **AND** that exact object is the one `StrategyRuntimeOrchestrator` uses for
  every background cycle across every strategy instance

#### Scenario: Single keyed-mutex-registry instance
- **WHEN** the production graph is constructed
- **THEN** exactly one `StrategyInstanceKeyedMutexRegistry` object is created
- **AND** that exact object is the one `StrategyRuntimeOrchestrator` uses to
  serialize every strategy instance's critical section

#### Scenario: Reusable by a future second writer
- **WHEN** the composition root finishes construction
- **THEN** the constructed repository and keyed-mutex-registry instances
  remain reachable from the composition root (not only closed over privately
  and unreachably)
- **AND** a future change may pass the same two instances into a second
  writer without reconstructing either

### Requirement: Outbound HTTP clients are constructed once and closed once
The composition root SHALL be the single owner of the four production HTTP
clients (`HttpxStrategyEngineLiveEntryAdapter`,
`HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
`HttpxAbiEntryPackageAdapter`): each SHALL be constructed exactly once at
application construction, reused across every background committed-bar cycle,
and closed exactly once at application shutdown.

#### Scenario: Construct once, reuse across cycles
- **WHEN** the composed application processes multiple committed-bar cycles,
  across one or many strategy instances
- **THEN** the same four HTTP client instances handle every outbound call
- **AND** no HTTP client is constructed per request or per background cycle

#### Scenario: Close every owned client on shutdown
- **WHEN** the application shuts down after a successful ready construction
- **THEN** each of the four owned HTTP clients is closed exactly once
- **AND** no owned client is left open

#### Scenario: Partial construction failure closes what was built
- **WHEN** constructing the four HTTP clients fails partway (e.g., a later
  client's configuration is invalid after earlier clients already constructed)
- **THEN** every client already constructed before the failure is closed
- **AND** `build_application` returns a not-ready application instead of a
  partially constructed production graph

#### Scenario: No caller closes a shared client directly
- **WHEN** a background cycle or an outbound adapter call completes, whether
  successfully or with a failure
- **THEN** no code path other than application shutdown calls `close()` on any
  of the four owned clients

### Requirement: Production configuration gates ready composition fail-closed
Strategy Runtime SHALL require `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`, and
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` for the default production
construction path (`strategy_cycle_handoff` not supplied), and SHALL never
return a partially constructed *ready* production graph. Outbound HTTP
clients are constructed in a deterministic order; a later constructor may
reject invalid configuration after one or more earlier clients already
constructed successfully — that is allowed as a transient construction-time
state, but it always closes every client already constructed and yields
`ready=False` rather than a ready application missing some outbound client.

#### Scenario: Valid configuration constructs a ready graph
- **WHEN** all five variables are present, each base URL is an absolute
  `http`/`https` URL, and each timeout is a finite positive number
- **THEN** `build_application` constructs the complete production graph
- **AND** the resulting application reports `ready=True`

#### Scenario: Missing or invalid configuration fails closed before any client is built
- **WHEN** any of the five variables is missing, or the first client's
  configuration in the construction order is invalid
- **THEN** `build_application` constructs no outbound HTTP client
- **AND** the resulting application reports `ready=False`, matching the
  existing not-ready pattern already used for invalid `RuntimeConfig`

#### Scenario: A later construction-time rejection still fails closed
- **WHEN** one or more earlier outbound HTTP clients in the deterministic
  construction order already constructed successfully, and a later client's
  configuration is invalid (missing variable, non-`http`/`https` URL, or
  non-finite/non-positive timeout)
- **THEN** `build_application` closes every client already constructed before
  that rejection
- **AND** the resulting application reports `ready=False`
- **AND** no partially usable production graph — with some outbound clients
  constructed and others missing — is ever returned as `ready=True`

#### Scenario: One ABI base URL serves two independently timed-out adapters
- **WHEN** the production graph is constructed
- **THEN** `HttpxAbiOpenPositionLookupAdapter` and the existing
  `HttpxAbiEntryPackageAdapter` are both constructed from the same
  `RUNTIME_ABI_BASE_URL`
- **AND** each uses its own distinct timeout
  (`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS` and
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`, respectively)

#### Scenario: No speculative reliability configuration is added
- **WHEN** the five configuration fields are validated
- **THEN** no retry-count, circuit-breaker, or other speculative reliability
  policy field is introduced

### Requirement: Default production composition and test override are distinct construction modes
`build_application` SHALL treat `strategy_cycle_handoff is None` (default
production composition) and `strategy_cycle_handoff` supplied (explicit test
override) as two distinct construction modes that never blend: the five
outbound configuration fields and the four outbound HTTP clients belong only
to the default production mode.

#### Scenario: Five outbound fields are mandatory only for the default path
- **WHEN** `build_application` is called without a `strategy_cycle_handoff`
  override
- **THEN** all five outbound configuration fields are required for the
  application to report `ready=True`

#### Scenario: Explicit override preserves the existing utility-only path
- **WHEN** `build_application` is called with an explicit
  `strategy_cycle_handoff` override and only the existing utility-only
  configuration (`RUNTIME_SPECS_PATH`, `RUNTIME_JOURNAL_PATH`)
- **THEN** the application reports `ready=True` without any of the five
  outbound configuration fields present
- **AND** none of the four outbound HTTP clients, the shared repository, the
  shared keyed-mutex registry, or the semantic Runtime graph is constructed

#### Scenario: No unused outbound resource is constructed under override
- **WHEN** an explicit `strategy_cycle_handoff` override is supplied
- **THEN** `build_application` does not construct any outbound HTTP client,
  since the override path never uses one

### Requirement: Two acknowledgement boundaries remain distinct
Strategy Runtime SHALL treat the MDS webhook acknowledgement and the ABI
entry-package acknowledgement as two independent confirmation boundaries, and
SHALL NOT let a downstream outcome change the already-sent HTTP response or
let the HTTP acknowledgement authorize any state mutation.

#### Scenario: HTTP acknowledgement authorizes nothing beyond acceptance
- **WHEN** Runtime returns `200 {"status":"accepted"}` for a valid, ready
  webhook request
- **THEN** that response does not assert that Strategy Engine projected
  successfully, that ABI acknowledged an entry package, that Runtime state was
  saved, or that an exchange order was placed, amended, or filled

#### Scenario: Only ABI acknowledgement authorizes state application
- **WHEN** `EntryReconciliationOrchestrator` holds a command-bearing decision
  (`Apply`, `Replace`, or `Cancel`)
- **THEN** it applies the reconciliation result and allows
  `StrategyRuntimeOrchestrator` to save replacement state only after receiving
  `EntryAppliedConfirmation` or `EntryAbsentConfirmation` from the entry
  -execution bridge
- **AND** no unconfirmed outcome from Strategy Engine, ABI open-position
  lookup, or ABI entry-package produces a save

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
`InMemoryStrategyInstanceRuntimeStateRepository` for `I4d`'s production graph,
and SHALL treat the resulting non-durable behavior as an accepted Live V1
limitation rather than an unresolved task of this change.

#### Scenario: In-memory repository is the selected implementation
- **WHEN** the production graph is constructed
- **THEN** the shared state repository is
  `InMemoryStrategyInstanceRuntimeStateRepository`
- **AND** `infrastructure/runtime_state/sqlite_repository.py` remains an
  unimplemented placeholder, not a partially completed component of this
  change

#### Scenario: A lost in-flight cycle is an accepted risk
- **WHEN** Runtime terminates after acknowledging a webhook but before its
  background committed-bar cycle completes
- **THEN** that in-flight cycle is lost with no persisted pending action,
  replay, or recovery mechanism
- **AND** this is documented as an accepted Live V1 limitation, matching the
  existing single-process, single-worker, non-durable concurrency model
