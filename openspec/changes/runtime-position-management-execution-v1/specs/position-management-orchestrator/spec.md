## ADDED Requirements

### Requirement: Runtime exposes a two-action position-management execution port taking only the command
Runtime SHALL define `PositionManagementExecutionPort` with exactly two
operations: `apply_protection(command: ApplyProtectionCommand) ->
ProtectionAppliedConfirmation` and `close_position(command:
ClosePositionCommand) -> PositionClosedConfirmation`. Neither operation
SHALL receive `StrategyInstanceRuntimeState` or any other Runtime aggregate;
each command already carries every value the operation needs.

#### Scenario: Two typed operations, command only
- **WHEN** the position-management execution port is defined
- **THEN** it exposes `apply_protection` and `close_position`, each
  accepting only its own command type
- **AND** neither operation's signature includes `source_state` or any
  other Runtime aggregate

#### Scenario: Port implementations receive no raw Engine or recipe value
- **WHEN** either port method is called
- **THEN** it receives only the typed command, never a raw
  `OpenTradeProjection`, `PositionManagementRecipe`, or
  `PositionManagementDecision` value

### Requirement: Commands and confirmations carry only identity and payload
`ApplyProtectionCommand` SHALL contain exactly `strategy_instance_id`,
`trade_cycle_id`, and `desired_protection: DesiredProtection`.
`ClosePositionCommand` SHALL contain exactly `strategy_instance_id` and
`trade_cycle_id`, with no quantity or `close_fraction` field — issuing it
means the entire current position closes. `ProtectionAppliedConfirmation`
SHALL contain exactly `strategy_instance_id`, `trade_cycle_id`, and
`confirmed_protection: DesiredProtection`. `PositionClosedConfirmation`
SHALL contain exactly `strategy_instance_id` and `trade_cycle_id`. None of
the four types SHALL contain an exchange order id, remaining quantity, fill
fact, or other execution-lifecycle detail.

#### Scenario: Reject malformed commands and confirmations
- **WHEN** any of the four types is constructed with an empty
  `strategy_instance_id`/`trade_cycle_id`, or a wrong-typed protection field
- **THEN** construction fails before the value can be used

#### Scenario: Close command and confirmation carry no quantity
- **WHEN** `ClosePositionCommand` or `PositionClosedConfirmation` is
  constructed
- **THEN** it carries no absolute quantity, percentage, or `close_fraction`
  field

### Requirement: A confirmation is a terminal, verified fact, not an acceptance acknowledgement
`PositionManagementExecutionPort.apply_protection` SHALL return
`ProtectionAppliedConfirmation` only once the executor has verified the
requested protection is actually applied. `close_position` SHALL return
`PositionClosedConfirmation` only once the executor has verified no open
position remainder exists. A response that only means the request was
accepted, submitted, or queued is not a confirmation and SHALL NOT be
returned as one.

#### Scenario: Protection confirmation requires verified application
- **WHEN** an executor has only accepted a protection-change request but not
  yet verified it took effect
- **THEN** it SHALL NOT return `ProtectionAppliedConfirmation`

#### Scenario: Close confirmation requires a verified zero remainder
- **WHEN** an executor has only accepted or submitted a close request but
  has not verified the position is fully closed
- **THEN** it SHALL NOT return `PositionClosedConfirmation`

### Requirement: NoOp performs no port call and leaves state unchanged
`PositionManagementOrchestrator.execute` SHALL call neither port method and
SHALL return the source state unmodified when the decision is `NoOp`.

#### Scenario: NoOp sends nothing to the execution port
- **WHEN** `decide_position_management` selects `NoOp` for a projection
- **THEN** the orchestrator calls neither `apply_protection` nor
  `close_position`
- **AND** it returns `projection.source.resolved_state.runtime_state`
  unchanged, by identity-equivalent value

### Requirement: The orchestrator composes decision, one port call, and a fail-closed confirmed state replacement
Runtime SHALL expose `PositionManagementOrchestrator.execute(projection:
OpenTradeProjectedStrategyInstance) -> StrategyInstanceRuntimeState` that
reads `source_state` from `projection.source.resolved_state.runtime_state`,
calls the existing `decide_position_management`, and — for a command-bearing
decision — calls exactly the matching port method once and applies its
confirmation through the `current-trade-cycle-state` capability's
confirmation-application rules, raising
`PositionManagementExecutionInvariantError` and returning no state on any
mismatch.

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

### Requirement: The orchestrator owns no mutex or repository
`PositionManagementOrchestrator` SHALL NOT acquire the keyed
strategy-instance mutex, load or save repository state, or perform retries
or pending-command bookkeeping.

#### Scenario: No coordination or persistence inside the orchestrator
- **WHEN** `PositionManagementOrchestrator.execute` runs
- **THEN** it acquires no keyed mutex, performs no repository load or save,
  and performs no retry of a failed port call
