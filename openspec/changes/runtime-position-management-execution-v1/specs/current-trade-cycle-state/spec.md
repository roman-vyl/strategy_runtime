## ADDED Requirements

### Requirement: Position-management execution changes current-cycle state only after matching confirmation
`StrategyInstanceRuntimeState.current_trade_cycle` SHALL change due to
position-management execution only after a successful confirmation from
`PositionManagementExecutionPort` matches the expected decision, the
ownership identities, and the sent command.

#### Scenario: Update confirmed protection after matching apply confirmation
- **WHEN** `ApplyProtection` receives a matching `ProtectionAppliedConfirmation`
- **THEN** Runtime replaces
  `current_trade_cycle.latest_confirmed_management_protection` with the
  confirmed value
- **AND** `trade_cycle_id`, `applied_entry_package`, and
  `frozen_entry_context` on that cycle remain unchanged

#### Scenario: Clear the current cycle after matching close confirmation
- **WHEN** `ClosePosition` receives a matching `PositionClosedConfirmation`
- **THEN** Runtime sets `current_trade_cycle` to null
- **AND** no partial or provisional cycle remains

#### Scenario: Preserve state after contradictory formal success
- **WHEN** a formally successful confirmation contradicts the expected
  decision variant, ownership identities, sent command, or the current
  trade cycle's `trade_cycle_id`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** the input `StrategyInstanceRuntimeState` remains unmodified and
  domain-value-equivalent to its pre-call snapshot

#### Scenario: Every valid position-management transition preserves the non-empty-cycle invariant
- **WHEN** a matching `ApplyProtection` or `ClosePosition` confirmation is
  applied successfully
- **THEN** the resulting state contains either null `current_trade_cycle`
  or one complete cycle with one required `AppliedEntryPackage`
- **AND** no valid transition produces an empty or partially populated
  current cycle
