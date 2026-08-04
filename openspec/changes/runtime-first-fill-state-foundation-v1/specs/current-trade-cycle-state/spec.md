## MODIFIED Requirements

### Requirement: Current trade cycle has only the minimal I2 fields
`CurrentTradeCycle` SHALL contain exactly one non-empty `trade_cycle_id`, one
required `applied_entry_package: AppliedEntryPackage`, and one nullable
`frozen_entry_context: FrozenExecutedEntryContext | null`.

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

#### Scenario: Represent a cycle before any fill
- **WHEN** `frozen_entry_context` is null
- **THEN** the cycle still retains its `trade_cycle_id` and
  `applied_entry_package`
- **AND** Runtime makes no claim that any exchange fill has occurred

#### Scenario: Exclude deferred fill-lifecycle and execution-phase state
- **WHEN** a current cycle is modeled
- **THEN** it contains no execution phase, filled quantity, remaining
  quantity, average entry price, fill ledger, or position-management recipe
  anywhere on the cycle or on any non-null `frozen_entry_context`

## ADDED Requirements

### Requirement: Frozen executed entry context is the minimal pre-I5 first-fill freeze
`FrozenExecutedEntryContext` SHALL contain exactly `desired_entry:
DesiredEntry`, a strictly positive integer `first_fill_at_ms`, and a
non-negative integer `entry_bar_open_time_ms`.

#### Scenario: Preserve one singular desired entry
- **WHEN** a frozen executed entry context is constructed
- **THEN** it contains one complete `DesiredEntry` under `desired_entry`
- **AND** `CurrentTradeCycle` does not duplicate that desired entry as
  another field outside `applied_entry_package`/`frozen_entry_context`

#### Scenario: Reject invalid context fields
- **WHEN** `desired_entry` has the wrong type, `first_fill_at_ms` is not a
  strictly positive integer, or `entry_bar_open_time_ms` is not a
  non-negative integer
- **THEN** context construction fails before the value can enter aggregate
  or repository state

#### Scenario: Keep price, quantity, and phase out of the frozen context
- **WHEN** a frozen executed entry context is constructed
- **THEN** it contains no average execution price, filled quantity,
  remaining quantity, fill ledger entry, or execution phase
- **AND** it is not the full future `I5` target shape that also carries
  `executed_entry_price`

### Requirement: The current trade cycle gains its frozen executed entry context only through the first-fill transition
`CurrentTradeCycle.frozen_entry_context` SHALL remain null until the
Runtime-owned first-fill transition (defined by the `first-fill-transition`
capability) successfully applies a fill for that cycle, and once set SHALL
retain the exact `FrozenExecutedEntryContext` produced by that transition.

#### Scenario: No frozen context before any recorded fill
- **WHEN** no fill has ever been successfully applied for a trade cycle
- **THEN** its `frozen_entry_context` remains null
- **AND** Runtime makes no claim about whether ABI or the exchange has
  filled any order for that cycle

#### Scenario: One frozen context after the first recorded fill
- **WHEN** the first-fill transition has successfully applied a fill for a
  trade cycle
- **THEN** that cycle's `frozen_entry_context` is the one
  `FrozenExecutedEntryContext` the transition produced
- **AND** no separate, second, or partially-populated frozen context exists
  alongside it
