## ADDED Requirements

### Requirement: Touch-trigger reconciliation holds the acknowledged entry
Runtime SHALL provide a pure decision function
`touch_trigger_entry_reconciliation(new_desired_entry, current_trade_cycle)`
that returns one of the existing closed decision variants and never `Cancel`
or `Replace`. When no current trade cycle exists it SHALL decide exactly as
`decide_entry_reconciliation` (`NoOp` for a null projection, `Apply` carrying
the new desired entry otherwise). When an acknowledged applied entry exists it
SHALL return `NoOp` whatever the new desired entry is. It SHALL apply the same
input type checks and the same fail-closed check on
`current_trade_cycle.frozen_entry_context` as `decide_entry_reconciliation`.
`decide_entry_reconciliation` SHALL remain unchanged.

#### Scenario: First desired entry is applied
- **WHEN** `current_trade_cycle` is null
- **AND** the new desired entry is non-null
- **THEN** the decision is `Apply` carrying that desired entry unchanged

#### Scenario: Nothing to apply
- **WHEN** `current_trade_cycle` is null
- **AND** the new desired entry is null
- **THEN** the decision is `NoOp`

#### Scenario: Null projection does not cancel a held entry
- **WHEN** an acknowledged applied entry exists
- **AND** the new desired entry is null
- **THEN** the decision is `NoOp`
- **AND** it is not `Cancel`

#### Scenario: Changed projection does not replace a held entry
- **WHEN** an acknowledged applied entry exists
- **AND** the new desired entry is non-null and not equivalent to it
- **THEN** the decision is `NoOp`
- **AND** it is not `Replace`

#### Scenario: Equal projection
- **WHEN** an acknowledged applied entry exists
- **AND** the new desired entry is equivalent to it
- **THEN** the decision is `NoOp`

#### Scenario: Fail closed once the entry context is frozen
- **WHEN** `current_trade_cycle.frozen_entry_context` is not null
- **THEN** `touch_trigger_entry_reconciliation` raises
  `EntryReconciliationInvariantError`

#### Scenario: Pure function
- **WHEN** `touch_trigger_entry_reconciliation` executes
- **THEN** it performs no HTTP, ABI-port, repository, mutex, Engine, clock or
  identity-factory operation
