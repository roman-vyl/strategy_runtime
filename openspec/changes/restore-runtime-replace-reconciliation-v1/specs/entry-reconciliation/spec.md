## ADDED Requirements

### Requirement: Reconciliation produces the complete four-variant decision table
Runtime SHALL produce exactly one closed payload-bearing decision variant from
`NoOp`, `Apply`, `Replace`, and `Cancel`. `Replace` is a logical decision
("the acknowledged package must be replaced by the new desired entry"); it
implies no ABI amend or atomic replace capability. Its physical execution is
owned by `entry-reconciliation-orchestrator`.

#### Scenario: No new or applied entry
- **WHEN** the new desired entry is null
- **AND** `current_trade_cycle` is null
- **THEN** the decision is `NoOp`
- **AND** carries no desired entry or trade-cycle identity

#### Scenario: First desired entry
- **WHEN** the new desired entry is non-null
- **AND** `current_trade_cycle` is null
- **THEN** the decision is `Apply`
- **AND** carries that new desired entry
- **AND** carries no trade-cycle identity

#### Scenario: Equivalent desired entry is already applied
- **WHEN** the new desired entry is equivalent to the acknowledged applied
  desired entry
- **THEN** the decision is `NoOp`

#### Scenario: Applied desired entry changed
- **WHEN** the new desired entry is non-null
- **AND** it is not equivalent to the acknowledged applied desired entry
- **THEN** the decision is `Replace`
- **AND** carries the acknowledged current `trade_cycle_id`
- **AND** carries the new desired entry unchanged

#### Scenario: Applied desired entry became absent
- **WHEN** the new desired entry is null
- **AND** an acknowledged applied package exists
- **THEN** the decision is `Cancel`
- **AND** carries the acknowledged current `trade_cycle_id`

#### Scenario: Replace is a validated value
- **WHEN** a `Replace` value is constructed
- **THEN** `trade_cycle_id` is a non-empty string
- **AND** `desired_entry` is a `DesiredEntry`
- **AND** construction fails otherwise

#### Scenario: Replace is never built into a single command
- **WHEN** the command builder or the successful-confirmation applier
  receives `Replace`
- **THEN** it raises `EntryReconciliationInvariantError`
- **AND** only the orchestrator's decomposition into `Cancel` and `Apply`
  reaches those components

## REMOVED Requirements

### Requirement: Reconciliation produces the complete three-way decision table
**Reason**: The 2026-08-16 collapse of `Replace` into `Cancel` mixed the
logical decision with its physical execution and left no order on every
second bar while the desired entry kept changing.
**Migration**: Replaced by "Reconciliation produces the complete
four-variant decision table". A changed desired entry now decides `Replace`;
a null desired entry still decides `Cancel`.
