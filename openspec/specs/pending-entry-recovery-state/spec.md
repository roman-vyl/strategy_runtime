# pending-entry-recovery-state Specification

## Purpose

TBD - Update Purpose after archive: the minimal `PendingEntryRecovery` sibling
aggregate field (`trade_cycle_id` only) and its relationship to
`current_trade_cycle`.

## Requirements

### Requirement: Strategy-instance state owns at most one minimal pending entry-recovery marker
`StrategyInstanceRuntimeState` SHALL contain `pending_entry_recovery:
PendingEntryRecovery | None`, a sibling field of `current_trade_cycle`, where
null means no entry mutation is currently uncertain for that instance.

#### Scenario: Represent no uncertain entry mutation
- **WHEN** `pending_entry_recovery` is null
- **THEN** Runtime has no reason to believe any ABI-side entry mutation for
  this instance is currently in an unresolved state
- **AND** the normal committed-bar pipeline (open-position resolution,
  routing, reconciliation) proceeds without deferral

#### Scenario: Represent one uncertain entry mutation
- **WHEN** `pending_entry_recovery` is non-null
- **THEN** exactly one `PendingEntryRecovery` is present
- **AND** the aggregate cannot contain a second concurrent pending marker

### Requirement: PendingEntryRecovery has only the one field needed to ask ABI which trade cycle is uncertain
`PendingEntryRecovery` SHALL contain exactly one non-empty `trade_cycle_id:
str` and no other field. It SHALL contain no `action` discriminator, no
`desired_entry`, no timestamp, no retry counter, and no command identifier.
There is no wall-clock recovery horizon in this design (see the paired
`uncertain-exchange-state-resolver` capability), so no field exists to
measure elapsed time against.

#### Scenario: Require a non-empty trade-cycle identity
- **WHEN** `PendingEntryRecovery` is constructed
- **THEN** `trade_cycle_id` is a non-empty string
- **AND** construction fails before the value can enter aggregate or
  repository state if it is empty or not a string

#### Scenario: No timestamp is stored
- **WHEN** `PendingEntryRecovery` is constructed
- **THEN** it contains no creation time, last-attempt time, or any other
  clock-derived field

#### Scenario: No desired entry is stored
- **WHEN** `PendingEntryRecovery` is constructed
- **THEN** it contains no `desired_entry`, `side`, price, quantity, stop, or
  take field — reconstructing an uncertain live entry's applied package (when
  ABI's recovery-state response reports it) reads that data from ABI's
  response, not from a value Runtime separately remembered

#### Scenario: No discriminator between an uncertain create and an uncertain removal
- **WHEN** `PendingEntryRecovery` is constructed
- **THEN** it carries no field distinguishing whether it originated from an
  `Apply` or a `Cancel` — that distinction is read from whether
  `current_trade_cycle` is null or holds the trade cycle being removed, not
  stored redundantly on the marker itself

### Requirement: The marker's trade_cycle_id identifies the same cycle current_trade_cycle would, never a different one
When `pending_entry_recovery` and `current_trade_cycle` are both non-null,
`pending_entry_recovery.trade_cycle_id` SHALL equal
`current_trade_cycle.trade_cycle_id`.

#### Scenario: An uncertain removal targets the current cycle
- **WHEN** an uncertain mutation exists for a trade cycle Runtime already
  acknowledges (an uncertain `Cancel`)
- **THEN** `pending_entry_recovery.trade_cycle_id` equals
  `current_trade_cycle.trade_cycle_id`

#### Scenario: An uncertain create has no current cycle to match
- **WHEN** an uncertain mutation exists for a trade cycle Runtime has not yet
  acknowledged (an uncertain `Apply`)
- **THEN** `current_trade_cycle` is null
- **AND** `pending_entry_recovery.trade_cycle_id` is the identity reserved
  for that not-yet-acknowledged cycle

### Requirement: A non-null pending marker does not itself prove any exchange state
The presence of `pending_entry_recovery` SHALL NOT be treated as evidence of
what actually happened on the exchange — it records only that Runtime does
not yet know.

#### Scenario: Pending does not mean applied
- **WHEN** `pending_entry_recovery` is non-null for an uncertain `Apply`
- **THEN** Runtime makes no claim that the corresponding order or position
  exists on the exchange

#### Scenario: Pending does not mean removed
- **WHEN** `pending_entry_recovery` is non-null for an uncertain `Cancel`
- **THEN** Runtime makes no claim that the corresponding order has been
  cancelled or that no position resulted from it

### Requirement: No file rewrite is required to introduce this field
Introducing `pending_entry_recovery` SHALL NOT require rewriting, migrating,
or compacting any previously durable record (see `runtime-durable-state-store`
for the `schema_version` 1→2 decode rule this depends on).

#### Scenario: Existing instances are unaffected until their next save
- **WHEN** the durable store contains instances saved before this field
  existed
- **THEN** those instances decode with `pending_entry_recovery = null` and
  behave exactly as before this change, until their state is next saved
