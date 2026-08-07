## REMOVED Requirements

### Requirement: Open-trade projection is explicitly unsupported
**Reason**: `PositionManagementOrchestrator` and its HTTP implementation of
`PositionManagementExecutionPort` are now ratified and available. The
open-trade application operation this requirement deferred is exactly
`PositionManagementOrchestrator.execute(...)`.
**Migration**: See the new "Open-trade projection invokes the existing
nested operation" requirement below, and the modified "Runtime dispatches
post-Engine results by supported typed projection variant" and "Runtime
saves only a logical aggregate transition" requirements. Callers of
`StrategyRuntimeOrchestrator.process(...)`/`.dispatch(...)` are otherwise
unaffected — the signatures and return shapes are unchanged; only the
open-trade branch's outcome changes from an always-raised error to a
supported result.

## ADDED Requirements

### Requirement: Open-trade projection invokes the existing nested operation
For an exact `OpenTradeProjectedStrategyInstance`,
`StrategyRuntimeOrchestrator` SHALL invoke the existing
`PositionManagementOrchestrator.execute(projection)` exactly once inside the
already-held keyed critical section.

#### Scenario: Pass the exact projection
- **WHEN** the router returns one open-trade projection
- **THEN** the nested orchestrator receives that exact projection object as
  its only operation argument
- **AND** no separately loaded or derived state is supplied as a second
  argument

#### Scenario: Preserve nested source-state ownership
- **WHEN** the nested operation executes
- **THEN** it remains responsible for extracting the exact source aggregate
  from `projection.source.resolved_state.runtime_state`
- **AND** the top-level orchestrator does not reload state for
  position-management
- **AND** the top-level orchestrator does not reproduce position-management
  decision, command, execution, or confirmation-application rules

#### Scenario: Return the nested aggregate result
- **WHEN** the nested operation returns a logically unchanged or replacement
  `StrategyInstanceRuntimeState`
- **THEN** `process(...)` uses that aggregate as its final state result
- **AND** invokes the nested operation no more than once

#### Scenario: The nested orchestrator receives no repository or mutex access
- **WHEN** `StrategyRuntimeOrchestrator` constructs or invokes
  `PositionManagementOrchestrator`
- **THEN** it does not pass `StrategyInstanceRuntimeStateRepository` or
  `StrategyInstanceKeyedMutexRegistry` to it
- **AND** the outer orchestrator remains the sole owner of the keyed
  critical section and of the save decision, exactly as for the live-entry
  branch

## MODIFIED Requirements

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
- **AND** coordinates the existing repository, resolver, router, and the
  selected nested application operation (`EntryReconciliationOrchestrator`
  or `PositionManagementOrchestrator`) as separate components

#### Scenario: Return final aggregate state
- **WHEN** either the live-entry or the open-trade branch completes
  successfully
- **THEN** `process(...)` returns the final
  `StrategyInstanceRuntimeState`
- **AND** does not return a `LiveEntryProjectedStrategyInstance`,
  `OpenTradeProjectedStrategyInstance`, reconciliation or
  position-management decision, command, confirmation, or dispatch outcome

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
- **WHEN** a live-entry or open-trade invocation progresses normally
- **THEN** the same keyed critical section remains held through repository
  get-or-create, position resolution, router and Engine projection, the
  selected nested application operation, and any required save
- **AND** neither the nested `EntryReconciliationOrchestrator` nor the
  nested `PositionManagementOrchestrator` reacquires the keyed mutex

#### Scenario: Release after successful completion
- **WHEN** a live-entry or open-trade invocation completes as either logical
  `NoOp` or saved replacement
- **THEN** the keyed critical section is released after the final aggregate is
  determined and any required save has completed
- **AND** a later same-instance invocation can acquire the key

#### Scenario: Release after any exception
- **WHEN** repository get-or-create, position resolution, router or Engine
  projection, the selected nested application operation, typed branch
  validation, or repository save raises an exception
- **THEN** the original or branch-specific exception propagates
- **AND** the keyed critical section is released
- **AND** a later same-instance invocation can acquire the key

### Requirement: Runtime dispatches post-Engine results by supported typed projection variant
After the router returns, `StrategyRuntimeOrchestrator` SHALL select behavior
from the supported typed projection variants and SHALL NOT use string,
mapping-shape, attribute-presence, or class-name dispatch.

#### Scenario: Select the live-entry branch
- **WHEN** the router returns an exact
  `LiveEntryProjectedStrategyInstance`
- **THEN** the orchestrator enters only the live-entry reconciliation branch

#### Scenario: Select the open-trade branch
- **WHEN** the router returns an exact
  `OpenTradeProjectedStrategyInstance`
- **THEN** the orchestrator enters only the position-management branch

#### Scenario: Fail closed for an unknown projection type
- **WHEN** the router returns any value whose runtime type is neither
  `LiveEntryProjectedStrategyInstance` nor
  `OpenTradeProjectedStrategyInstance`
- **THEN** `process(...)` raises `UnknownStrategyProjectionError`
- **AND** does not call entry reconciliation or position management
- **AND** does not call repository `save(...)`
- **AND** does not use a fallback branch or return a successful result

### Requirement: Runtime saves only a logical aggregate transition
For either branch, `StrategyRuntimeOrchestrator` SHALL compare the selected
nested operation's resulting aggregate with
`projection.source.resolved_state.runtime_state` using the existing immutable
aggregate value equality and SHALL issue a post-projection repository
`save(...)` only for a value-different replacement. This rule governs only
the post-projection save decision; it applies identically whether the
nested operation was `EntryReconciliationOrchestrator.execute(...)` or
`PositionManagementOrchestrator.execute(...)`, and it is independent of
whether an earlier first-fill freeze save already completed in the same
invocation.

#### Scenario: Logical NoOp performs no post-projection save
- **WHEN** the selected nested operation returns an aggregate value-equal to
  the projection's embedded source aggregate
- **THEN** no post-projection repository `save(...)` is called
- **AND** `process(...)` returns the value-equivalent final aggregate
- **AND** an already-completed first-fill freeze save for this invocation,
  if any, remains in effect — a post-projection `NoOp` never reverts it

#### Scenario: Object allocation does not imply transition
- **WHEN** the selected nested operation returns a different Python object
  that is value-equal to the projection's embedded source aggregate
- **THEN** no post-projection repository `save(...)` is called
- **AND** the orchestrator does not use `resulting_state is not source_state` as
  a change test

#### Scenario: Confirmed transition saves exactly once
- **WHEN** the selected nested operation returns a complete
  `StrategyInstanceRuntimeState` that is value-different from the embedded
  source aggregate
- **THEN** the orchestrator passes that complete replacement aggregate to
  repository `save(...)` exactly once as the post-projection save
- **AND** calls no partial-field repository operation
- **AND** returns the exact `StrategyInstanceRuntimeState` returned by
  repository `save(...)`, not the pre-save input aggregate
- **AND** the invocation's total repository `save(...)` call count is one if
  no first-fill freeze save preceded it, or two if a first-fill freeze save
  already completed earlier in the same invocation — the post-projection
  save is always exactly one of those calls, never a substitute for or a
  repetition of the freeze save

#### Scenario: Use no redundant change result
- **WHEN** the orchestrator decides whether a post-projection save is
  required
- **THEN** it uses the existing `StrategyInstanceRuntimeState` value equality
- **AND** does not introduce a new result DTO solely to carry `changed: bool`

### Requirement: Closed-bar semantic errors propagate without recovery
`StrategyRuntimeOrchestrator.process(...)` SHALL propagate dependency and
semantic errors without retry, fallback, suppression, conversion into `NoOp`,
or construction of a failed dispatch outcome.

#### Scenario: Propagate state-load failure
- **WHEN** repository `get_or_create(...)` raises
- **THEN** that exception propagates
- **AND** position resolution, Engine projection, the nested application
  operation, and repository save are not invoked

#### Scenario: Propagate position-resolution failure
- **WHEN** the open-position resolver raises
- **THEN** that exception propagates
- **AND** router and Engine projection, the nested application operation, and
  repository save are not invoked

#### Scenario: Propagate Engine projection failure
- **WHEN** the use-case router or selected Strategy Engine projection raises
- **THEN** that exception propagates
- **AND** the nested application operation and the post-projection
  repository save are not invoked
- **AND** an already-completed first-fill freeze save, if the position was
  open, is not reverted, repeated, or treated as satisfying the
  post-projection save

#### Scenario: Propagate reconciliation failure
- **WHEN** `EntryReconciliationOrchestrator.execute(projection)` raises
- **THEN** that exception propagates
- **AND** the post-projection repository `save(...)` is not invoked
- **AND** reconciliation is not retried or replaced by a fallback

#### Scenario: Propagate position-management failure
- **WHEN** `PositionManagementOrchestrator.execute(projection)` raises
- **THEN** that exception propagates
- **AND** the post-projection repository `save(...)` is not invoked
- **AND** position management is not retried or replaced by a fallback
- **AND** an already-completed first-fill freeze save is not reverted or
  repeated by this failure

#### Scenario: Propagate save failure
- **WHEN** the post-projection repository `save(...)` raises for a
  value-different replacement
- **THEN** that exception propagates after exactly one post-projection save
  attempt
- **AND** the orchestrator performs no retry, compensating write, fallback, or
  successful return
- **AND** an already-completed first-fill freeze save earlier in the same
  invocation, if any, already succeeded and is unaffected by this failure

#### Scenario: Persist no partial replacement on error
- **WHEN** the use-case router, selected Strategy Engine projection, the
  nested application operation, or the post-projection repository save
  raises
- **THEN** no post-projection repository `save(...)` call occurs for that
  invocation
- **AND** an already-completed first-fill freeze save from earlier in the
  same invocation, if any, is unaffected — neither repeated nor reverted
- **AND** no partial nested-operation aggregate is persisted
- **AND** neither a deterministic initial aggregate created by
  `get_or_create(...)` nor an already-completed first-fill freeze save is
  treated as a partially applied nested-operation transition

#### Scenario: Rely on atomic repository rejection
- **WHEN** the repository rejects a complete replacement during `save(...)`
- **THEN** the existing repository atomic-save contract preserves the prior
  complete stored aggregate
- **AND** the top-level orchestrator performs no partial merge or second save
