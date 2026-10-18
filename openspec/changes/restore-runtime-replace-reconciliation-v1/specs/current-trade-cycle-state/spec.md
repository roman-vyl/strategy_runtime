## MODIFIED Requirements

### Requirement: Entry reconciliation changes current-cycle state only after matching confirmation
`StrategyInstanceRuntimeState.current_trade_cycle` SHALL change for entry
reconciliation only after a successful confirmation matches the expected
action, ownership identities, originating command, and source-state
preconditions. Runtime never atomically replaces the `AppliedEntryPackage`
in place. A changed applied desired entry is served by `Replace`, executed as
a confirmed `Cancel` of the current cycle followed, in the same invocation,
by an `Apply` with a new `trade_cycle_id`; each step changes state only after
its own matching confirmation.

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

#### Scenario: Clear the complete cycle after successful cancel
- **WHEN** `Cancel` receives a matching `EntryAbsentConfirmation` for the
  acknowledged current cycle
- **THEN** Runtime sets `current_trade_cycle` to null
- **AND** does not construct or retain a `CurrentTradeCycle` with a null applied
  package
- **AND** this holds identically for a `Cancel` decision and for the cancel
  step of a `Replace` decision

#### Scenario: Every valid transition preserves the non-empty-cycle invariant
- **WHEN** `Apply` or `Cancel` completes successfully
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

#### Scenario: Replace moves to a new cycle only through two confirmations
- **WHEN** `Replace(C, Y)` executes
- **THEN** cycle C is cleared only after a matching `EntryAbsentConfirmation`
- **AND** a cycle N with applied desired entry Y is created only after a
  matching `EntryAppliedConfirmation`
- **AND** N differs from C
