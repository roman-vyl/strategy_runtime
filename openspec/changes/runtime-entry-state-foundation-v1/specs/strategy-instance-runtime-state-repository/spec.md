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
The repository SHALL accept a typed request containing all data required to
create the initial state without querying another module.

#### Scenario: Map identity, deployment, and risk fields
- **WHEN** `StrategyRuntimeOrchestrator` builds the request
- **THEN** it supplies `strategy_instance_id` and `strategy_id`
- **AND** supplies instrument and base timeframe
- **AND** supplies the complete `raw_spec`
- **AND** supplies source path
- **AND** copies the deployment's required top-level `risk_multiplier` exactly

#### Scenario: Exclude invocation-specific and utility-internal data
- **WHEN** the request is constructed
- **THEN** it contains no committed-bar data
- **AND** contains no deployment-content hash
- **AND** contains no utility selection metadata

#### Scenario: Keep risk separate from raw spec
- **WHEN** the request transports `raw_spec` and `risk_multiplier`
- **THEN** they remain separate request fields
- **AND** the request does not insert risk configuration into `raw_spec`

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
- **AND** stores the request's exact user-provided positive exact-decimal `risk_multiplier`
- **AND** returns the created aggregate

#### Scenario: Create no default risk value
- **WHEN** the registration request omits risk multiplier or supplies an invalid value
- **THEN** request or state construction fails
- **AND** the repository does not substitute `"1"` or any other default
- **AND** no aggregate is created

#### Scenario: Create no trade-cycle state
- **WHEN** the initial aggregate is created
- **THEN** `current_trade_cycle` is null
- **AND** no trade-cycle identity or applied entry package is created
- **AND** this null Runtime state makes no claim about exchange order or position existence

#### Scenario: Keep risk outside immutable spec snapshot and identity
- **WHEN** initial state is created
- **THEN** `risk_multiplier` is a separate strategy-instance state field
- **AND** is not added to `registered_spec_snapshot`
- **AND** did not participate in `strategy_instance_id` derivation

### Requirement: Existing state is returned without mutation
The repository SHALL return an existing state without replacing its registered
snapshot, overwriting its stored risk multiplier, or changing its current-cycle
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
- **WHEN** repeated deployment discovery supplies the same identity with another valid `risk_multiplier`
- **THEN** get-or-create preserves the multiplier already stored in Runtime state
- **AND** does not treat discovery as a risk-update operation
- **AND** does not create, clear, or replace the current cycle or applied entry package
