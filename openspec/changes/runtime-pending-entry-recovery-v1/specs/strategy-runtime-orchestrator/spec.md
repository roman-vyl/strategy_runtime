## MODIFIED Requirements

### Requirement: Runtime coordinates one semantic processing unit through final aggregate application
Strategy Runtime SHALL provide
`StrategyRuntimeOrchestrator.process(unit:
StrategyBarProcessingUnit[DeploymentSpecification]) ->
StrategyInstanceRuntimeState` to coordinate one processing unit through state
get-or-create, a pending-entry-recovery guard, authoritative open-position
resolution, use-case routing, Strategy Engine projection, typed
post-projection handling, and final aggregate state return.

#### Scenario: Execute the existing projection pipeline in order
- **WHEN** `process(...)` receives one `StrategyBarProcessingUnit`
- **THEN** it calls
  `StrategyInstanceRuntimeStateRepository.get_or_create(...)` exactly once
- **AND**, when the returned state's `pending_entry_recovery` is null, passes
  that state to the open-position resolver exactly once
- **AND**, for a temporally eligible processing unit (see "Runtime applies
  the first-fill transition before routing an open position"), passes the
  original processing unit and resolved state to `StrategyUseCaseRouter`
  exactly once
- **AND** receives the router's typed Strategy Engine projection before
  selecting a post-projection branch

#### Scenario: A pending entry-recovery marker defers the entire pipeline
- **WHEN** the state returned by `get_or_create(...)` has a non-null
  `pending_entry_recovery`
- **THEN** `process(...)` returns that state immediately, without calling the
  open-position resolver, `StrategyUseCaseRouter`, Strategy Engine, the
  first-fill transition, `EntryReconciliationOrchestrator`, or
  `PositionManagementOrchestrator`
- **AND** performs no repository `save(...)` for this invocation
- **AND** this guard runs before the open-position resolver specifically
  because an uncertain removal leaves `current_trade_cycle` set, and an
  unguarded open-position lookup against an ABI-side unresolved status fails
  closed with `500` — the guard exists to prevent that, not only to prevent a
  new entry decision

#### Scenario: Keep delegated rules in their existing components
- **WHEN** `process(...)` executes the projection pipeline
- **THEN** it does not reproduce authoritative position-resolution rules
- **AND** does not reproduce use-case routing or Engine request-mapping rules
- **AND** does not construct either Engine projection type
- **AND** does not reproduce `uncertain-exchange-state-resolver`'s resolution
  rules
- **AND** coordinates the existing repository, resolver, router, and the
  selected nested application operation (`EntryReconciliationOrchestrator`
  or `PositionManagementOrchestrator`) as separate components

#### Scenario: Return final aggregate state
- **WHEN** either the live-entry or the open-trade branch completes
  successfully, or the pending-entry-recovery guard applies
- **THEN** `process(...)` returns the final
  `StrategyInstanceRuntimeState`
- **AND** does not return a `LiveEntryProjectedStrategyInstance`,
  `OpenTradeProjectedStrategyInstance`, reconciliation or
  position-management decision, command, confirmation, or dispatch outcome

### Requirement: Closed-bar semantic errors propagate without recovery
`StrategyRuntimeOrchestrator.process(...)` SHALL propagate dependency and
semantic errors without retry, fallback, suppression, conversion into `NoOp`,
or construction of a failed dispatch outcome. A processing unit deferred by
the pending-entry-recovery guard is not an error: it is a successful `process(
...)` return carrying the unchanged current state, and `dispatch(...)` reports
it as an ordinary successful outcome, exactly like an unchanged post-projection
result.

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
