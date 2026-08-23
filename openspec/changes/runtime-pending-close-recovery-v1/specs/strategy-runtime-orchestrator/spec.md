## MODIFIED Requirements

### Requirement: Runtime coordinates one semantic processing unit through final aggregate application
Strategy Runtime SHALL provide
`StrategyRuntimeOrchestrator.process(unit:
StrategyBarProcessingUnit[DeploymentSpecification]) ->
StrategyInstanceRuntimeState` to coordinate one processing unit through state
get-or-create, a pending-recovery guard, authoritative open-position
resolution, use-case routing, Strategy Engine projection, typed
post-projection handling, and final aggregate state return. The
pending-recovery guard SHALL defer the pipeline when either
`pending_entry_recovery` or `pending_close_recovery` is non-null.

#### Scenario: Execute the existing projection pipeline in order
- **WHEN** `process(...)` receives one `StrategyBarProcessingUnit`
- **THEN** it calls
  `StrategyInstanceRuntimeStateRepository.get_or_create(...)` exactly once
- **AND**, when the returned state's `pending_entry_recovery` and
  `pending_close_recovery` are both null, passes that state to the
  open-position resolver exactly once
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

#### Scenario: A pending close-recovery marker defers the entire pipeline
- **WHEN** the state returned by `get_or_create(...)` has a non-null
  `pending_close_recovery`
- **THEN** `process(...)` returns that state immediately, without calling the
  open-position resolver, `StrategyUseCaseRouter`, Strategy Engine, the
  first-fill transition, `EntryReconciliationOrchestrator`, or
  `PositionManagementOrchestrator`
- **AND** performs no repository `save(...)` for this invocation
- **AND** this uses the same single guard check and the same position in the
  pipeline as the `pending_entry_recovery` guard — no second gate
  abstraction is introduced

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
  successfully, or the pending-recovery guard applies
- **THEN** `process(...)` returns the final
  `StrategyInstanceRuntimeState`
- **AND** does not return a `LiveEntryProjectedStrategyInstance`,
  `OpenTradeProjectedStrategyInstance`, reconciliation or
  position-management decision, command, confirmation, or dispatch outcome
