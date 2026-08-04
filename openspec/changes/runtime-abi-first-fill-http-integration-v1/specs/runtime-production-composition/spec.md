## MODIFIED Requirements

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

### Requirement: Runtime composes exactly one production live-entry graph
`strategy_runtime.bootstrap.application.build_application` SHALL construct,
for every `ready=True` result, the complete production graph from the
existing utility contour through the existing semantic core and existing
outbound adapters to the existing `AbiEntryPackagePort` HTTP client, using
only components already implemented and tested in isolation by prior
changes, and SHALL additionally construct exactly one
`AbiExecutionEventOrchestrator` and connect it to `create_http_app(...)` as
the first-fill application callable. There is no caller-supplied override
that replaces any part of this graph, and no construction path returns
`ready=True` with only part of it.

#### Scenario: Compose the existing components, not new ones
- **WHEN** `build_application` constructs a ready application
- **THEN** it constructs `OpenPositionResolver`, `StrategyUseCaseRouter`,
  `EntryReconciliationOrchestrator`, `StrategyRuntimeOrchestrator`, and
  `AbiExecutionEventOrchestrator` from their existing, unmodified
  constructors
- **AND** it constructs `HttpxStrategyEngineLiveEntryAdapter`,
  `HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
  and the existing `HttpxAbiEntryPackageAdapter` from their existing,
  unmodified constructors
- **AND** it introduces no new top-level orchestrator, reconciliation
  component, or outbound adapter class beyond the already-shipped
  `AbiExecutionEventOrchestrator`
- **AND** it introduces no new outbound HTTP client

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
  skip constructing any of the four outbound HTTP clients
- **AND** every `ready=True` application it returns has the complete graph
  constructed — there is no alternative utility-only `ready=True` result

### Requirement: Production configuration gates ready composition fail-closed
Strategy Runtime SHALL require `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
`RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
`RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`, and
`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` unconditionally for any
`ready=True` result of `build_application`, and SHALL never return a
partially constructed *ready* production graph. Two distinct failure stages
exist: config loading/parsing (a missing required variable, or a timeout
string that cannot parse to `float`) happens before any outbound HTTP
client is constructed; adapter-constructor validation (a
malformed/non-absolute/non-HTTP(S) URL, a non-finite timeout, or a
zero/negative timeout) happens only during client construction, after zero
or more earlier clients already exist. Constructing
`AbiExecutionEventOrchestrator` and connecting its callable to
`create_http_app(...)` are mandatory steps inside this same fail-closed
boundary: a failure at either step yields `ready=False` exactly as a
failure in any earlier step already does, and introduces no new
environment variable of its own.

#### Scenario: Valid configuration constructs a ready graph
- **WHEN** all five variables are present, each base URL is an absolute
  `http`/`https` URL, and each timeout is a finite positive number
- **THEN** `build_application` constructs the complete production graph,
  including `AbiExecutionEventOrchestrator` and its connected first-fill
  callable
- **AND** the resulting application reports `ready=True`

#### Scenario: A missing or unparsable field fails closed before any client exists
- **WHEN** any of the five variables is missing, or a timeout variable
  cannot be parsed as a number
- **THEN** `build_application` constructs zero outbound HTTP clients and
  does not construct `AbiExecutionEventOrchestrator`
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
