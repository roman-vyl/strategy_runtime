## ADDED Requirements

### Requirement: Runtime exposes a two-action position-management execution port
Runtime SHALL define `PositionManagementExecutionPort` as a Runtime-owned
abstract boundary with exactly two operations: `apply_protection(command:
ApplyProtectionCommand, source_state: StrategyInstanceRuntimeState) ->
ProtectionAppliedConfirmation` and `close_position(command:
ClosePositionCommand, source_state: StrategyInstanceRuntimeState) ->
PositionClosedConfirmation`. Runtime SHALL NOT define a single combined
`execute` operation over a command union for this boundary.

#### Scenario: Two distinct typed operations
- **WHEN** the position-management execution port is defined
- **THEN** it exposes `apply_protection` and `close_position` as two separate
  methods, each with its own command and confirmation type
- **AND** no third method or combined command union exists on the port

#### Scenario: Port implementations receive no raw Engine or recipe value
- **WHEN** either port method is called
- **THEN** it receives only the typed command and the `source_state`
  snapshot, never a raw `OpenTradeProjection`, `PositionManagementRecipe`, or
  `PositionManagementDecision` value

### Requirement: Commands carry only Runtime-owned identity and payload
`ApplyProtectionCommand` SHALL contain exactly `strategy_instance_id`,
`trade_cycle_id`, and `desired_protection: DesiredProtection`.
`ClosePositionCommand` SHALL contain exactly `strategy_instance_id` and
`trade_cycle_id`. Neither command SHALL contain a quantity, `close_fraction`,
exchange order reference, or any other execution-lifecycle field.

#### Scenario: Apply-protection command is minimal
- **WHEN** `ApplyProtectionCommand` is constructed
- **THEN** it holds exactly `strategy_instance_id`, `trade_cycle_id`, and
  `desired_protection`
- **AND** construction rejects an empty `strategy_instance_id` or
  `trade_cycle_id`, or a `desired_protection` of the wrong type

#### Scenario: Close-position command carries no quantity or fraction
- **WHEN** `ClosePositionCommand` is constructed
- **THEN** it holds exactly `strategy_instance_id` and `trade_cycle_id`
- **AND** it carries no absolute quantity, percentage, or `close_fraction`
  field — issuing the command means the entire current position closes
- **AND** construction rejects an empty `strategy_instance_id` or
  `trade_cycle_id`

### Requirement: Confirmations carry only identity and confirmed payload
`ProtectionAppliedConfirmation` SHALL contain exactly `strategy_instance_id`,
`trade_cycle_id`, and `confirmed_protection: DesiredProtection`.
`PositionClosedConfirmation` SHALL contain exactly `strategy_instance_id` and
`trade_cycle_id`. Neither confirmation SHALL contain exchange fill facts,
order identifiers, remaining quantity, or any other execution-lifecycle
field.

#### Scenario: Protection-applied confirmation is minimal
- **WHEN** `ProtectionAppliedConfirmation` is constructed
- **THEN** it holds exactly `strategy_instance_id`, `trade_cycle_id`, and
  `confirmed_protection`
- **AND** construction rejects an empty identity field or a wrong-typed
  `confirmed_protection`

#### Scenario: Position-closed confirmation is minimal
- **WHEN** `PositionClosedConfirmation` is constructed
- **THEN** it holds exactly `strategy_instance_id` and `trade_cycle_id`
- **AND** it carries no remaining quantity, exchange order id, or fill fact

### Requirement: NoOp performs no port call and leaves state unchanged
`PositionManagementOrchestrator.execute` SHALL call neither port method and
SHALL return the source state unmodified when the position-management
decision is `NoOp`.

#### Scenario: NoOp sends nothing to the execution port
- **WHEN** `decide_position_management` selects `NoOp` for a projection
- **THEN** the orchestrator calls neither `apply_protection` nor
  `close_position`
- **AND** it returns `projection.source.resolved_state.runtime_state`
  unchanged, by identity-equivalent value

### Requirement: ApplyProtection execution updates confirmed protection only after a matching confirmation
Confirmed position-management execution SHALL change
`CurrentTradeCycle.latest_confirmed_management_protection` only after
`PositionManagementExecutionPort.apply_protection` returns a
`ProtectionAppliedConfirmation` whose `strategy_instance_id`,
`trade_cycle_id`, and `confirmed_protection` match the originating
`ApplyProtection` decision and its sent `ApplyProtectionCommand`.

#### Scenario: Apply a matching confirmed protection
- **WHEN** the decision is `ApplyProtection` for a trade cycle and the port
  returns a `ProtectionAppliedConfirmation` with the same
  `strategy_instance_id`, `trade_cycle_id`, and `confirmed_protection` equal
  to the decision's `desired_protection`
- **THEN** the resulting state's `CurrentTradeCycle
  .latest_confirmed_management_protection` equals the confirmed protection
- **AND** `trade_cycle_id`, `applied_entry_package`, and
  `frozen_entry_context` remain exactly as they were on the source state

#### Scenario: Reject a confirmation with different protection
- **WHEN** the returned `ProtectionAppliedConfirmation.confirmed_protection`
  differs from the decision's `desired_protection` or the sent command's
  `desired_protection`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** `current_trade_cycle` remains exactly as it was on the source state

### Requirement: ClosePosition execution clears the current trade cycle only after a matching confirmation
Confirmed position-management execution SHALL set
`StrategyInstanceRuntimeState.current_trade_cycle` to null only after
`PositionManagementExecutionPort.close_position` returns a
`PositionClosedConfirmation` whose `strategy_instance_id` and
`trade_cycle_id` match the originating `ClosePosition` decision and its sent
`ClosePositionCommand`.

#### Scenario: Clear the cycle after a matching close confirmation
- **WHEN** the decision is `ClosePosition` for a trade cycle and the port
  returns a `PositionClosedConfirmation` with the same `strategy_instance_id`
  and `trade_cycle_id`
- **THEN** the resulting state's `current_trade_cycle` is null
- **AND** no other field of `StrategyInstanceRuntimeState` changes

#### Scenario: Reject a confirmation for a different trade cycle
- **WHEN** the returned `PositionClosedConfirmation.trade_cycle_id` differs
  from the decision's `trade_cycle_id` or the sent command's
  `trade_cycle_id`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** `current_trade_cycle` remains exactly as it was on the source state

### Requirement: Confirmation application fails closed on any mismatch
Applying a position-management confirmation SHALL raise
`PositionManagementExecutionInvariantError`, and SHALL NOT modify the input
state, when the confirmation's type does not match the decision variant
(`ApplyProtection` requires `ProtectionAppliedConfirmation`, `ClosePosition`
requires `PositionClosedConfirmation`), when any `strategy_instance_id` does
not equal the source state's `strategy_instance_id`, or when the source
state has no current trade cycle or a `trade_cycle_id` that does not match
the decision.

#### Scenario: Wrong confirmation variant for the decision
- **WHEN** the decision is `ApplyProtection` but the port returns a
  `PositionClosedConfirmation`, or the decision is `ClosePosition` but the
  port returns a `ProtectionAppliedConfirmation`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** no state change occurs

#### Scenario: Strategy-instance identity mismatch
- **WHEN** the sent command's or the confirmation's `strategy_instance_id`
  does not equal `source_state.strategy_instance_id`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** no state change occurs

#### Scenario: Missing or mismatched current trade cycle
- **WHEN** `source_state.current_trade_cycle` is null, or its
  `trade_cycle_id` does not equal the decision's `trade_cycle_id`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** no state change occurs

### Requirement: The orchestrator composes decision, one port call, and confirmed state replacement
Runtime SHALL expose `PositionManagementOrchestrator.execute(projection:
OpenTradeProjectedStrategyInstance) -> StrategyInstanceRuntimeState` that
reads `source_state` from `projection.source.resolved_state.runtime_state`,
calls the existing `decide_position_management` with
`projection.position_management_recipe` and
`source_state.current_trade_cycle`, and — for a command-bearing decision —
calls exactly one matching port method before applying its confirmation.

#### Scenario: One port call per command-bearing decision
- **WHEN** the decision is `ApplyProtection`
- **THEN** the orchestrator calls `apply_protection` exactly once and never
  calls `close_position`
- **WHEN** the decision is `ClosePosition`
- **THEN** the orchestrator calls `close_position` exactly once and never
  calls `apply_protection`

#### Scenario: A port failure yields no new state
- **WHEN** either port method raises instead of returning a confirmation
- **THEN** `PositionManagementOrchestrator.execute` propagates that
  exception uncaught
- **AND** it returns no `StrategyInstanceRuntimeState`, so the caller never
  observes a partially applied result

### Requirement: The orchestrator owns no mutex or repository
`PositionManagementOrchestrator` SHALL NOT acquire the keyed
strategy-instance mutex, load or save repository state, or perform retries,
recovery, or pending-command bookkeeping. Those responsibilities remain
outside this boundary.

#### Scenario: No coordination or persistence inside the orchestrator
- **WHEN** `PositionManagementOrchestrator.execute` runs
- **THEN** it acquires no keyed mutex
- **AND** it performs no repository load or save
- **AND** it performs no retry of a failed port call
