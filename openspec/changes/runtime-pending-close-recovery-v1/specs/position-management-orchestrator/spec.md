## MODIFIED Requirements

### Requirement: The orchestrator composes decision, one port call, and a fail-closed confirmed state replacement
Runtime SHALL expose `PositionManagementOrchestrator.execute(projection:
OpenTradeProjectedStrategyInstance) -> StrategyInstanceRuntimeState` that
reads `source_state` from `projection.source.resolved_state.runtime_state`,
calls the existing `decide_position_management`, and — for a command-bearing
decision — calls exactly the matching port method once and applies its
confirmation through the `current-trade-cycle-state` capability's
confirmation-application rules, raising
`PositionManagementExecutionInvariantError` and returning no state on any
mismatch. For a `ClosePosition` decision specifically, the orchestrator
SHALL durably save `source_state` with `pending_close_recovery` set to a
`PendingCloseRecovery` for the target `trade_cycle_id` before calling
`close_position(command)`, mirroring `EntryReconciliationOrchestrator`'s
existing pre-write-before-dispatch ordering. If that pre-write itself fails,
`close_position` is never called.

#### Scenario: One matching port call per decision
- **WHEN** the decision is `ApplyProtection`
- **THEN** the orchestrator calls `apply_protection` exactly once and never
  `close_position`
- **WHEN** the decision is `ClosePosition`
- **THEN** the orchestrator calls `close_position` exactly once and never
  `apply_protection`

#### Scenario: A port failure or mismatched confirmation yields no new state
- **WHEN** the port raises instead of returning a confirmation, or returns a
  confirmation that fails the `current-trade-cycle-state` matching rules
- **THEN** `execute` raises (propagating the port's exception, or
  `PositionManagementExecutionInvariantError` for a mismatch)
- **AND** it returns no `StrategyInstanceRuntimeState`

#### Scenario: A ClosePosition decision durably saves the pending marker before dispatch
- **WHEN** `decide_position_management` selects `ClosePosition` for a
  `trade_cycle_id`
- **THEN** the orchestrator saves `source_state` with `pending_close_recovery
  = PendingCloseRecovery(trade_cycle_id)` before calling
  `close_position(command)`
- **AND** this save completes, durably, before the port method is invoked

#### Scenario: A failed pre-write never dispatches the close command
- **WHEN** the pre-write save for `pending_close_recovery` itself raises
- **THEN** the orchestrator does not call `close_position`
- **AND** the exception from the pre-write propagates unchanged

#### Scenario: A timed-out or lost close response leaves the marker in place for the resolver
- **WHEN** `close_position(command)` raises (for example on a client
  timeout) after the pre-write already durably saved
  `pending_close_recovery`
- **THEN** the orchestrator's exception propagates exactly as before this
  change
- **AND** the durably saved `pending_close_recovery` remains in place for
  `uncertain-exchange-state-resolver` to resolve later — no other component
  clears it on this path
