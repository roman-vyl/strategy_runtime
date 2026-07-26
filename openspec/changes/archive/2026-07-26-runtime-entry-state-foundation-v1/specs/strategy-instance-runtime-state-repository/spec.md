## ADDED Requirements

### Requirement: Repository loads existing state by strategy-instance identity
`StrategyInstanceRuntimeStateRepository` SHALL expose a scalar lookup that
returns the current complete aggregate for one exact `strategy_instance_id` or
null when that identity is not registered.

#### Scenario: Load an existing aggregate
- **WHEN** state exists for the supplied strategy-instance identity
- **THEN** `get(...)` returns the currently stored complete immutable aggregate

#### Scenario: Report a missing aggregate without creating it
- **WHEN** no state exists for the supplied strategy-instance identity
- **THEN** `get(...)` returns null
- **AND** does not create registration data, risk configuration, or a current cycle

#### Scenario: Reject an invalid lookup identity
- **WHEN** the lookup identity is empty or not a string
- **THEN** lookup fails before accessing repository state

### Requirement: Repository saves one complete existing aggregate
`StrategyInstanceRuntimeStateRepository` SHALL expose `save(...)` to atomically
replace one already registered aggregate with one complete valid
`StrategyInstanceRuntimeState`.

#### Scenario: Save a complete aggregate
- **WHEN** the aggregate identity is already registered and its immutable registration data matches
- **THEN** the repository replaces the stored value with the supplied complete aggregate
- **AND** returns the stored aggregate
- **AND** preserves the supplied valid `risk_multiplier` and current-cycle state
- **AND** performs no partial field merge

#### Scenario: Reject save for an unregistered identity
- **WHEN** no state is registered under the supplied aggregate's `strategy_instance_id`
- **THEN** save raises a typed state-not-found error
- **AND** does not create a new aggregate

#### Scenario: Reject registration mutation through save
- **WHEN** a supplied aggregate changes the persisted `strategy_id` or `registered_spec_snapshot`
- **THEN** save raises a typed identity or registration conflict
- **AND** preserves the previously stored aggregate unchanged

#### Scenario: Save no transport or orchestration behavior
- **WHEN** save succeeds
- **THEN** the repository has not called ABI, Strategy Engine, an HTTP handler, or a Runtime orchestrator

### Requirement: In-memory load and save operations are individually atomic
`InMemoryStrategyInstanceRuntimeStateRepository` SHALL protect each `get`,
`get_or_create`, and `save` operation from partial concurrent observation
within one process.

#### Scenario: Observe only complete saved values
- **WHEN** one caller saves a valid aggregate while another caller loads the same identity
- **THEN** lookup returns either the complete prior aggregate or the complete replacement
- **AND** never returns a partially merged state

#### Scenario: Make no multi-call transaction guarantee
- **WHEN** callers perform `get` followed later by `save`
- **THEN** the repository does not claim that the sequence is atomic
- **AND** does not detect stale snapshots or provide compare-and-swap
- **AND** future writers remain responsible for using keyed coordination

## MODIFIED Requirements

### Requirement: The request contains complete first-registration data
The repository SHALL accept a typed request containing deployment-derived
identity and immutable first-registration data without operational risk state.

#### Scenario: Map identity and registration fields
- **WHEN** `StrategyRuntimeOrchestrator` builds the request
- **THEN** it supplies `strategy_instance_id` and `strategy_id`
- **AND** supplies instrument and base timeframe
- **AND** supplies the complete `raw_spec`
- **AND** supplies source path

#### Scenario: Exclude operational and invocation-specific data
- **WHEN** the request is constructed
- **THEN** it contains no `risk_multiplier`
- **AND** contains no committed-bar data
- **AND** contains no deployment-content hash
- **AND** contains no utility selection metadata

#### Scenario: Keep freezing at the ownership boundary
- **WHEN** the request transports a mutable raw-spec mapping
- **THEN** the request is not required to detach or freeze it
- **AND** `RegisteredSpecSnapshot` owns validation, detachment, and recursive freezing during creation

### Requirement: Missing state is created as one complete aggregate
The repository SHALL atomically create a complete
`StrategyInstanceRuntimeState` when its `strategy_instance_id` is absent.

#### Scenario: Create the initial aggregate
- **WHEN** no state exists for the requested `strategy_instance_id`
- **THEN** the repository stores `strategy_instance_id` and `strategy_id`
- **AND** stores an immutable registered snapshot containing instrument, base timeframe, raw spec, and source path
- **AND** stores canonical initial `risk_multiplier` exactly as `"1"`
- **AND** returns the created aggregate

#### Scenario: Keep canonical initialization internal to Runtime
- **WHEN** the initial aggregate is created
- **THEN** `"1"` is supplied by the repository as canonical Runtime state
- **AND** it is not read from deployment, `raw_spec`, or the registration request
- **AND** no risk-update use case is executed

#### Scenario: Create no trade-cycle state
- **WHEN** the initial aggregate is created
- **THEN** `current_trade_cycle` is null
- **AND** no trade-cycle identity or applied entry package is created
- **AND** this null Runtime state does not replace ABI position lookup or prove that an exchange position is absent

#### Scenario: Keep risk outside immutable registration and identity
- **WHEN** initial state is created
- **THEN** `risk_multiplier` is a separate strategy-instance state field
- **AND** is not added to `registered_spec_snapshot`
- **AND** did not participate in `strategy_instance_id` derivation

### Requirement: Existing state is returned without mutation
The repository SHALL return an existing state without replacing its registered
snapshot, resetting its stored risk multiplier, or changing its current-cycle
content.

#### Scenario: Repeat an equivalent request
- **WHEN** the same get-or-create request is repeated
- **THEN** the repository returns the currently stored logical state
- **AND** does not create a duplicate aggregate

#### Scenario: Preserve the first registered snapshot
- **WHEN** a request reuses an existing `strategy_instance_id` and the same `strategy_id`
- **THEN** the repository returns the existing state
- **AND** does not compare or rewrite its registered snapshot
- **AND** treats the supplied derived identity as authoritative instead of revalidating instrument, base timeframe, or raw spec

#### Scenario: Preserve operational and cycle state
- **WHEN** deployment discovery repeats after a complete aggregate with another valid multiplier was saved
- **THEN** get-or-create preserves the multiplier already stored in Runtime state
- **AND** does not reset it to canonical initial `"1"`
- **AND** does not treat discovery as a risk-update operation
- **AND** does not create, clear, or replace the current cycle or applied entry package
