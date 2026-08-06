## ADDED Requirements

### Requirement: Runtime-issued position-management execution changes current-cycle state only after a matching confirmation
`StrategyInstanceRuntimeState.current_trade_cycle` SHALL change due to
Runtime-issued position-management execution only after a confirmation from
`PositionManagementExecutionPort` matches the originating decision's
ownership identities, action type, and (for protection) confirmed value.
This requirement governs only Runtime-issued `ApplyProtection` /
`ClosePosition` execution; it neither defines nor precludes a future
external-close lifecycle (e.g. Runtime reacting to ABI reporting
`position_open=false` after an exchange-side close).

#### Scenario: Update confirmed protection after a matching apply confirmation
- **WHEN** `ApplyProtection` receives a matching `ProtectionAppliedConfirmation`
- **THEN** Runtime replaces
  `current_trade_cycle.latest_confirmed_management_protection` with the
  confirmed value
- **AND** every other field of that cycle is unchanged

#### Scenario: Clear the current cycle after a matching close confirmation
- **WHEN** `ClosePosition` receives a matching `PositionClosedConfirmation`
- **THEN** Runtime sets `current_trade_cycle` to null

#### Scenario: Preserve state after a contradictory formal success
- **WHEN** a formally successful confirmation contradicts the expected
  action, ownership identities, sent command, or the current cycle's
  `trade_cycle_id`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** the input `StrategyInstanceRuntimeState` remains unmodified and
  domain-value-equivalent to its pre-call snapshot
