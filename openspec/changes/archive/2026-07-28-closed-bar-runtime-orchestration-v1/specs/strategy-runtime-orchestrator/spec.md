## REMOVED Requirements

### Requirement: Runtime coordinates one semantic processing unit through Engine projection
**Removed because:** The original stopping point was the Strategy Engine projection
(`StrategyUseCaseProjectedInstance`). This change extends orchestration through
typed branching, live-entry reconciliation, conditional persistence, and final
aggregate return. The original contract no longer describes the orchestrator's
responsibility.

**Migration:** Replaced by `Runtime coordinates one semantic processing unit
through final aggregate application` which preserves the same delegated pipeline
sequence and adds typed post-projection handling and aggregate-state return.

## MODIFIED Requirements

### Requirement: Runtime exposes the utility handoff dispatch contract
`StrategyRuntimeOrchestrator.dispatch(...)` SHALL remain a thin adapter from
semantic processing to the utility `StrategyCycleDispatchPort` contract.

#### Scenario: Dispatch one unit successfully
- **WHEN** `process(...)` returns final aggregate state without raising an error
- **THEN** `dispatch(...)` returns a successful
  `StrategyCycleDispatchOutcome`
- **AND** the outcome contains the processing unit's
  `strategy_instance_id`
- **AND** `dispatch(...)` does not expose the returned aggregate in that outcome

#### Scenario: Propagate semantic failure
- **WHEN** mutex acquisition, repository access, position resolution, Engine
  projection, typed branch handling, reconciliation, or save raises an error
- **THEN** `dispatch(...)` lets that error propagate
- **AND** does not create a failed or successful dispatch outcome
- **AND** does not retry, fall back, or convert the error into `NoOp`

#### Scenario: Preserve committed-bar failure ownership
- **WHEN** a `StrategyRuntimeOrchestrator.dispatch(...)` exception reaches
  `CommittedBarOrchestrator`
- **THEN** `CommittedBarOrchestrator` remains responsible for converting that
  exception into the existing failed per-unit dispatch outcome
- **AND** `StrategyRuntimeOrchestrator` does not duplicate that conversion

## ADDED Requirements

### Requirement: Runtime coordinates one semantic processing unit through final aggregate application
Strategy Runtime SHALL provide
`StrategyRuntimeOrchestrator.process(unit:
StrategyBarProcessingUnit[DeploymentSpecification]) ->
StrategyInstanceRuntimeState` to coordinate one processing unit through state
get-or-create, authoritative open-position resolution, use-case routing,
Strategy Engine projection, typed post-projection handling, and final aggregate
state return.

#### Scenario: Execute the existing projection pipeline in order
- **WHEN** `process(...)` receives one `StrategyBarProcessingUnit`
- **THEN** it calls
  `StrategyInstanceRuntimeStateRepository.get_or_create(...)` exactly once
- **AND** passes that returned state to the open-position resolver exactly once
- **AND** passes the original processing unit and resolved state to
  `StrategyUseCaseRouter` exactly once
- **AND** receives the router's typed Strategy Engine projection before
  selecting a post-projection branch

#### Scenario: Keep delegated rules in their existing components
- **WHEN** `process(...)` executes the projection pipeline
- **THEN** it does not reproduce authoritative position-resolution rules
- **AND** does not reproduce use-case routing or Engine request-mapping rules
- **AND** does not construct either Engine projection type
- **AND** coordinates the existing repository, resolver, router, and nested
  application operation as separate components

#### Scenario: Return final aggregate state
- **WHEN** the live-entry branch completes successfully
- **THEN** `process(...)` returns the final
  `StrategyInstanceRuntimeState`
- **AND** does not return a `LiveEntryProjectedStrategyInstance`,
  `OpenTradeProjectedStrategyInstance`, reconciliation decision, command,
  confirmation, or dispatch outcome

### Requirement: Runtime owns the complete keyed closed-bar critical section
`StrategyRuntimeOrchestrator` SHALL use the existing
`StrategyInstanceKeyedMutexRegistry` to hold the exact
`StrategyBarProcessingUnit.strategy_instance_id` key from before state load
until the closed-bar invocation returns or raises.

#### Scenario: Acquire before loading state
- **WHEN** `process(...)` starts one closed-bar invocation
- **THEN** it enters `hold(unit.strategy_instance_id)` before calling repository
  `get_or_create(...)`
- **AND** no Runtime-state snapshot is loaded before the keyed critical section
  is held

#### Scenario: Hold through every application stage
- **WHEN** a live-entry invocation progresses normally
- **THEN** the same keyed critical section remains held through repository
  get-or-create, position resolution, router and Engine projection,
  reconciliation, and any required save
- **AND** the nested `EntryReconciliationOrchestrator` does not reacquire the
  keyed mutex

#### Scenario: Release after successful completion
- **WHEN** a live-entry invocation completes as either logical `NoOp` or saved
  replacement
- **THEN** the keyed critical section is released after the final aggregate is
  determined and any required save has completed
- **AND** a later same-instance invocation can acquire the key

#### Scenario: Release after any exception
- **WHEN** repository get-or-create, position resolution, router or Engine
  projection, reconciliation, typed branch validation, or repository save
  raises an exception
- **THEN** the original or branch-specific exception propagates
- **AND** the keyed critical section is released
- **AND** a later same-instance invocation can acquire the key

### Requirement: Same-instance closed-bar invocations serialize
All `StrategyRuntimeOrchestrator` invocations sharing one keyed-mutex registry
and exact `strategy_instance_id` SHALL execute their complete state-bearing
workflow sequentially.

#### Scenario: Serialize two same-instance invocations
- **WHEN** one invocation holds the critical section for an instance and a
  second invocation starts for the same exact instance ID
- **THEN** the second invocation does not load state or enter another
  application stage until the first invocation releases the key
- **AND** their critical sections do not overlap

#### Scenario: Load fresh state after waiting
- **WHEN** a same-instance invocation waits while a preceding invocation saves
  replacement state
- **THEN** the waiting invocation calls `get_or_create(...)` only after it
  acquires the mutex
- **AND** its downstream pipeline receives the repository state available
  after the preceding invocation completed

### Requirement: Different strategy instances remain independent
Closed-bar coordination SHALL NOT serialize invocations solely because they use
the same `StrategyRuntimeOrchestrator` and keyed-mutex registry when their exact
strategy-instance IDs differ.

#### Scenario: Overlap two different-instance invocations
- **WHEN** two invocations use different valid strategy-instance IDs
- **THEN** both can enter their respective critical sections concurrently
- **AND** a blocked or slow stage for one instance does not prevent the other
  instance from progressing

### Requirement: Runtime dispatches post-Engine results by supported typed projection variant
After the router returns, `StrategyRuntimeOrchestrator` SHALL select behavior
from the supported typed projection variants and SHALL NOT use string,
mapping-shape, attribute-presence, or class-name dispatch.

#### Scenario: Select the live-entry branch
- **WHEN** the router returns an exact
  `LiveEntryProjectedStrategyInstance`
- **THEN** the orchestrator enters only the live-entry reconciliation branch

#### Scenario: Select the known open-trade branch
- **WHEN** the router returns an exact
  `OpenTradeProjectedStrategyInstance`
- **THEN** the orchestrator enters only the explicitly unsupported open-trade
  branch

#### Scenario: Fail closed for an unknown projection type
- **WHEN** the router returns any value whose runtime type is neither
  `LiveEntryProjectedStrategyInstance` nor
  `OpenTradeProjectedStrategyInstance`
- **THEN** `process(...)` raises `UnknownStrategyProjectionError`
- **AND** does not call entry reconciliation
- **AND** does not call repository `save(...)`
- **AND** does not use a fallback branch or return a successful result

### Requirement: Live-entry projection invokes the existing nested operation
For an exact `LiveEntryProjectedStrategyInstance`,
`StrategyRuntimeOrchestrator` SHALL invoke the existing
`EntryReconciliationOrchestrator.execute(projection)` exactly once inside the
already-held keyed critical section.

#### Scenario: Pass the exact projection
- **WHEN** the router returns one live-entry projection
- **THEN** the nested orchestrator receives that exact projection object as its
  only operation argument
- **AND** no separately loaded or derived state is supplied as a second
  argument

#### Scenario: Preserve nested source-state ownership
- **WHEN** the nested operation executes
- **THEN** it remains responsible for extracting the exact source aggregate
  from `projection.source.resolved_state.runtime_state`
- **AND** the top-level orchestrator does not reload state for reconciliation
- **AND** the top-level orchestrator does not reproduce reconciliation
  decision, command, execution, or confirmation-application rules

#### Scenario: Return the nested aggregate result
- **WHEN** the nested operation returns a logically unchanged or replacement
  `StrategyInstanceRuntimeState`
- **THEN** `process(...)` uses that aggregate as its final state result
- **AND** invokes the nested operation no more than once

### Requirement: Runtime saves only a logical aggregate transition
For the live-entry branch, `StrategyRuntimeOrchestrator` SHALL compare the
nested operation's resulting aggregate with
`projection.source.resolved_state.runtime_state` using the existing immutable
aggregate value equality and SHALL save only a value-different replacement.

#### Scenario: Logical NoOp performs no save
- **WHEN** reconciliation returns an aggregate value-equal to the projection's
  embedded source aggregate
- **THEN** repository `save(...)` is not called
- **AND** `process(...)` returns the value-equivalent final aggregate

#### Scenario: Object allocation does not imply transition
- **WHEN** reconciliation returns a different Python object that is value-equal
  to the projection's embedded source aggregate
- **THEN** repository `save(...)` is not called
- **AND** the orchestrator does not use `resulting_state is not source_state` as
  a change test

#### Scenario: Confirmed transition saves exactly once
- **WHEN** the nested operation returns a complete
  `StrategyInstanceRuntimeState` that is value-different from the embedded
  source aggregate
- **THEN** the orchestrator passes that complete replacement aggregate to
  repository `save(...)` exactly once
- **AND** calls no partial-field repository operation
- **AND** returns the exact `StrategyInstanceRuntimeState` returned by
  repository `save(...)`, not the pre-save input aggregate

#### Scenario: Use no redundant change result
- **WHEN** the orchestrator decides whether persistence is required
- **THEN** it uses the existing `StrategyInstanceRuntimeState` value equality
- **AND** does not introduce a new result DTO solely to carry `changed: bool`

### Requirement: Open-trade projection is explicitly unsupported
Until an open-trade application operation is separately designed,
`StrategyRuntimeOrchestrator` SHALL reject an exact
`OpenTradeProjectedStrategyInstance` with
`OpenTradeProjectionUnsupportedError`.

#### Scenario: Reject the deferred open-trade branch
- **WHEN** the router returns an exact
  `OpenTradeProjectedStrategyInstance`
- **THEN** `process(...)` raises `OpenTradeProjectionUnsupportedError`
- **AND** does not call `EntryReconciliationOrchestrator`
- **AND** does not call repository `save(...)`
- **AND** does not return the projection or another successful result
- **AND** does not allow `dispatch(...)` to report success

### Requirement: Closed-bar semantic errors propagate without recovery
`StrategyRuntimeOrchestrator.process(...)` SHALL propagate dependency and
semantic errors without retry, fallback, suppression, conversion into `NoOp`,
or construction of a failed dispatch outcome.

#### Scenario: Propagate state-load failure
- **WHEN** repository `get_or_create(...)` raises
- **THEN** that exception propagates
- **AND** position resolution, Engine projection, reconciliation, and
  repository save are not invoked

#### Scenario: Propagate position-resolution failure
- **WHEN** the open-position resolver raises
- **THEN** that exception propagates
- **AND** router and Engine projection, reconciliation, and repository save are
  not invoked

#### Scenario: Propagate Engine projection failure
- **WHEN** the use-case router or selected Strategy Engine projection raises
- **THEN** that exception propagates
- **AND** reconciliation and repository save are not invoked

#### Scenario: Propagate reconciliation failure
- **WHEN** `EntryReconciliationOrchestrator.execute(projection)` raises
- **THEN** that exception propagates
- **AND** repository `save(...)` is not invoked
- **AND** reconciliation is not retried or replaced by a fallback

#### Scenario: Propagate save failure
- **WHEN** repository `save(...)` raises for a value-different replacement
- **THEN** that exception propagates after exactly one save attempt
- **AND** the orchestrator performs no retry, compensating write, fallback, or
  successful return

#### Scenario: Persist no partial replacement on error
- **WHEN** any error occurs before repository save
- **THEN** repository `save(...)` has zero calls for that invocation
- **AND** no partial reconciliation aggregate is persisted
- **AND** a deterministic initial aggregate created by `get_or_create(...)`, if
  any, is not treated as a partially applied reconciliation transition

#### Scenario: Rely on atomic repository rejection
- **WHEN** the repository rejects a complete replacement during `save(...)`
- **THEN** the existing repository atomic-save contract preserves the prior
  complete stored aggregate
- **AND** the top-level orchestrator performs no partial merge or second save
