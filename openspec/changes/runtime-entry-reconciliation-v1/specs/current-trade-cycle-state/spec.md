## MODIFIED Requirements

### Requirement: Strategy-instance state owns at most one minimal current cycle
`StrategyInstanceRuntimeState` SHALL contain
`current_trade_cycle: CurrentTradeCycle | null`, where null means Runtime owns
no acknowledged current trade cycle.

#### Scenario: Represent no Runtime-owned acknowledged current cycle
- **WHEN** `current_trade_cycle` is null
- **THEN** Runtime state contains no acknowledged current-cycle identity or
  applied entry package
- **AND** Runtime makes no claim that an exchange order or real position is absent

#### Scenario: Nest one acknowledged current cycle
- **WHEN** `current_trade_cycle` is non-null
- **THEN** exactly one complete `CurrentTradeCycle` with one required
  `AppliedEntryPackage` is nested under that strategy instance
- **AND** the aggregate cannot contain a second concurrent current cycle

### Requirement: Current trade cycle has only the minimal I2 fields
`CurrentTradeCycle` SHALL contain exactly one non-empty `trade_cycle_id` and
one required `applied_entry_package: AppliedEntryPackage`.

#### Scenario: Require an acknowledged applied package
- **WHEN** `CurrentTradeCycle` is constructed
- **THEN** `applied_entry_package` is a complete `AppliedEntryPackage`
- **AND** it cannot be null

#### Scenario: Reject an empty current cycle
- **WHEN** `applied_entry_package` is null or has the wrong type
- **THEN** cycle construction fails before the value can enter aggregate or
  repository state
- **AND** Runtime defines no recovery, compatibility, or transitional semantics
  for that invalid value

#### Scenario: Exclude deferred execution state
- **WHEN** a current cycle is modeled
- **THEN** it contains no phase, frozen execution context, filled quantity, remaining quantity, average entry price, fill timestamp, fill ledger, or position-management recipe

### Requirement: Applied entry package is one indivisible nested value
`AppliedEntryPackage` SHALL contain exactly `applied_desired_entry` and
`calculated_quantity`.

#### Scenario: Preserve one singular desired entry
- **WHEN** an applied package is constructed
- **THEN** it contains one complete `DesiredEntry` under `applied_desired_entry`
- **AND** `CurrentTradeCycle` does not duplicate that desired entry as another field
- **AND** no separate long and short applied-entry objects exist

#### Scenario: Preserve confirmed quantity lexeme
- **WHEN** a valid confirmed quantity string is supplied
- **THEN** `calculated_quantity` is finite exact-decimal text
- **AND** the accepted lexeme is retained without binary floating-point conversion or textual normalization

#### Scenario: Reject invalid package fields
- **WHEN** applied desired entry has the wrong type or calculated quantity is not finite exact-decimal text
- **THEN** package construction fails before the value can enter repository state

#### Scenario: Keep wire and exchange details outside the package
- **WHEN** an applied package is stored
- **THEN** it contains no HTTP status, response envelope, exchange order payload, stop reference, take reference, fill fact, or execution phase

### Requirement: Minimal current-cycle state does not prove exchange state
The presence or absence of a Runtime-owned acknowledged current cycle SHALL NOT
be treated as authoritative proof of current exchange order or position
existence.

#### Scenario: Acknowledged current cycle is absent
- **WHEN** `current_trade_cycle` is null
- **THEN** Runtime owns no acknowledged current-cycle identity or applied
  package
- **AND** an ABI lookup remains authoritative for exchange position facts

#### Scenario: Acknowledged current cycle exists
- **WHEN** `current_trade_cycle` is non-null
- **THEN** Runtime owns its complete acknowledged entry package
- **AND** that state alone does not prove the package remains pending, has
  filled, or corresponds to a currently open exchange position
- **AND** an ABI lookup remains authoritative for current exchange position facts

## ADDED Requirements

### Requirement: Entry reconciliation changes current-cycle state only after matching confirmation
`StrategyInstanceRuntimeState.current_trade_cycle` SHALL change for entry
reconciliation only after a successful confirmation matches the expected
action, ownership identities, originating command, and source-state
preconditions.

#### Scenario: Create a cycle after successful apply
- **WHEN** `Apply` receives a matching `EntryAppliedConfirmation`
- **AND** source `current_trade_cycle` is null
- **THEN** Runtime creates `CurrentTradeCycle` only after that confirmation
- **AND** sets its `trade_cycle_id` to the acknowledged target identity
- **AND** stores one complete `AppliedEntryPackage` containing the acknowledged
  desired entry and calculated quantity

#### Scenario: Do not create a cycle before apply confirmation
- **WHEN** an `Apply` command is constructed
- **THEN** the source state's current-cycle value remains unchanged
- **AND** the caller-selected trade-cycle identity is not inserted into the
  aggregate merely because it was reserved or sent

#### Scenario: Replace the complete package after successful replace
- **WHEN** `Replace` receives a matching `EntryAppliedConfirmation` for the
  acknowledged current cycle
- **THEN** Runtime retains the existing `trade_cycle_id`
- **AND** atomically replaces the entire `AppliedEntryPackage` with the
  acknowledged desired entry and calculated quantity
- **AND** does not create a new trade cycle

#### Scenario: Clear the complete cycle after successful cancel
- **WHEN** `Cancel` receives a matching `EntryAbsentConfirmation` for the
  acknowledged current cycle
- **THEN** Runtime sets `current_trade_cycle` to null
- **AND** does not construct or retain a `CurrentTradeCycle` with a null applied
  package

#### Scenario: Every valid transition preserves the non-empty-cycle invariant
- **WHEN** `Apply`, `Replace`, or `Cancel` completes successfully
- **THEN** resulting state contains either null `current_trade_cycle` or one
  complete cycle with one required `AppliedEntryPackage`
- **AND** no valid transition produces an empty current cycle

#### Scenario: Preserve state after contradictory formal success
- **WHEN** a formally successful confirmation contradicts the expected
  action, ownership identities, sent desired entry, or source-state
  preconditions
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** the input `StrategyInstanceRuntimeState` remains unmodified and
  domain-value-equivalent to its pre-call snapshot
- **AND** no empty, partial, pending, or provisional current cycle is stored
