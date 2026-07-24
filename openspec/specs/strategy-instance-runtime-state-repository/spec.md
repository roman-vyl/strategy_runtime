# strategy-instance-runtime-state-repository Specification

## Purpose

Define the scalar Runtime repository boundary that atomically gets or creates
one in-memory strategy-instance state from an authoritative utility-derived
deployment identity.

## Requirements

### Requirement: Runtime provides one strategy-instance state repository boundary
Strategy Runtime SHALL provide
`StrategyInstanceRuntimeStateRepository.get_or_create(...)` as the first
semantic operation performed by `StrategyRuntimeOrchestrator.process(...)`.

#### Scenario: Invoke the repository from the Runtime Orchestrator
- **WHEN** the utility pipeline hands one `StrategyBarProcessingUnit` to `StrategyRuntimeOrchestrator`
- **THEN** the orchestrator constructs one typed get-or-create request
- **AND** invokes the repository exactly once for that processing unit
- **AND** receives one `StrategyInstanceRuntimeState` into the same `process(...)` call

#### Scenario: Keep downstream processing outside the repository
- **WHEN** the repository returns a state
- **THEN** the repository does not call the Open Position Resolver
- **AND** does not route a Strategy Engine use case
- **AND** does not call Strategy Engine or ABI

### Requirement: The repository uses the utility-derived strategy-instance identity
The repository SHALL use `StrategyBarProcessingUnit.strategy_instance_id` as the
unique key of `StrategyInstanceRuntimeState` and SHALL NOT derive another
repository identity.

#### Scenario: Use the supplied derived identity
- **WHEN** the orchestrator constructs the get-or-create request
- **THEN** it copies `StrategyBarProcessingUnit.strategy_instance_id`
- **AND** the repository uses that value as its lookup and creation key

#### Scenario: Keep strategy type distinct from instance identity
- **WHEN** requests for different `strategy_instance_id` values share one `strategy_id`
- **THEN** the repository stores separate strategy-instance states

### Requirement: The request contains complete first-registration data
The repository SHALL accept a typed request containing all data required to
create the initial state without querying another module.

#### Scenario: Map identity and deployment fields
- **WHEN** `StrategyRuntimeOrchestrator` builds the request
- **THEN** it supplies `strategy_instance_id` and `strategy_id`
- **AND** supplies `instrument` and `base_timeframe`
- **AND** supplies the complete `raw_spec`
- **AND** supplies `source_path`

#### Scenario: Exclude invocation-specific and utility-internal data
- **WHEN** the request is constructed
- **THEN** it contains no committed-bar data
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
- **AND** returns the created aggregate

#### Scenario: Create no trade-cycle state
- **WHEN** the initial aggregate is created
- **THEN** `current_trade_cycle` is null
- **AND** no `trade_cycle_id` or recipe is created
- **AND** no position fact or management projection is stored

### Requirement: Existing state is returned without mutation
The repository SHALL return an existing state without replacing its registered
snapshot or changing its trade-cycle content.

#### Scenario: Repeat an equivalent request
- **WHEN** the same get-or-create request is repeated
- **THEN** the repository returns the existing logical state
- **AND** does not create a duplicate aggregate

#### Scenario: Preserve the first registered snapshot
- **WHEN** a request reuses an existing `strategy_instance_id` and the same `strategy_id`
- **THEN** the repository returns the existing state
- **AND** does not compare or rewrite its registered snapshot
- **AND** treats the supplied derived identity as authoritative instead of revalidating instrument, base timeframe, or raw spec
- **AND** does not create, clear, replace, or freeze a trade cycle or recipe

### Requirement: Conflicting strategy type is rejected
The repository SHALL reject reuse of one `strategy_instance_id` for a different
persisted `strategy_id`.

#### Scenario: Detect a strategy identity conflict
- **WHEN** state exists under the requested `strategy_instance_id`
- **AND** the request's `strategy_id` differs from the persisted `strategy_id`
- **THEN** the repository raises `StrategyInstanceIdentityConflict`
- **AND** does not modify the persisted state

### Requirement: In-memory get-or-create is atomic and idempotent
`InMemoryStrategyInstanceRuntimeStateRepository` SHALL guarantee one complete
logical state per `strategy_instance_id` under repeated or concurrent equivalent
calls within one process.

#### Scenario: Concurrent first creation
- **WHEN** equivalent calls concurrently request the same absent `strategy_instance_id`
- **THEN** exactly one aggregate object is stored
- **AND** every successful caller receives that same object
- **AND** no caller observes a partially created aggregate

#### Scenario: Make no physical durability guarantee
- **WHEN** the in-memory repository returns a state
- **THEN** the capability guarantees neither restart recovery nor cross-process persistence
