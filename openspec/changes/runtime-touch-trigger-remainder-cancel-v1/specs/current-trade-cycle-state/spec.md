## MODIFIED Requirements

### Requirement: Current trade cycle has only the minimal Runtime-owned fields
`CurrentTradeCycle` SHALL contain exactly one non-empty `trade_cycle_id`, one
required `applied_entry_package: AppliedEntryPackage`, one nullable
`frozen_entry_context: FrozenExecutedEntryContext | null`, and one nullable
latest confirmed management protection:
`latest_confirmed_management_protection: DesiredProtection | null`. Null
means Runtime has not yet acknowledged any post-entry management change;
the initial protection remains available from
`frozen_entry_context.desired_entry` regardless. Runtime SHALL store only
this single latest confirmed value, never a history. `CurrentTradeCycle`
SHALL also contain one required boolean `entry_remainder_cancelled`, `false`
on construction, which becomes `true` only when ABI confirmed that the
cycle's entry order has no live remainder (entry-remainder-cancel
capability) and never returns to `false` for that cycle. It is open-trade
execution state, not part of the frozen recipe, and carries no quantity,
phase, or exchange identifier.

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

#### Scenario: Exclude deferred execution state
- **WHEN** a current cycle is modeled
- **THEN** it contains no phase, filled quantity, remaining quantity,
  average entry price, fill timestamp, or fill ledger anywhere on the
  cycle or on any non-null `frozen_entry_context`
- **AND** it contains no protection history, pending execution state,
  diagnostics, or full `PositionManagementRecipe` — only the single
  nullable latest confirmed management protection

#### Scenario: No management acknowledgement yet
- **WHEN** a current trade cycle has never had a management protection
  acknowledged
- **THEN** its latest confirmed management protection is null
- **AND** its initial protection is still readable from
  `frozen_entry_context.desired_entry`

#### Scenario: One replaceable acknowledged value
- **WHEN** a current trade cycle's latest confirmed management protection
  is set
- **THEN** it holds exactly one `DesiredProtection` value
- **AND** no prior acknowledged protection, pending change, or diagnostics
  value is retained alongside it

#### Scenario: A new cycle has no confirmed remainder cancel
- **WHEN** a `CurrentTradeCycle` is constructed by Apply
- **THEN** `entry_remainder_cancelled` is `false`

#### Scenario: The remainder mark is a boolean only
- **WHEN** `entry_remainder_cancelled` is not a boolean
- **THEN** cycle construction fails before the value can enter aggregate or repository state

### Requirement: Frozen executed entry context is the minimal first-fill freeze
`FrozenExecutedEntryContext` SHALL contain exactly `desired_entry:
DesiredEntry`, a strictly positive integer `first_fill_at_ms` (type checked,
`> 0`), and a non-negative integer `entry_bar_open_time_ms` (type checked,
`>= 0`) where `entry_bar_open_time_ms <= first_fill_at_ms`, and
`entry_order_expires_at_bar`: a non-negative integer or `null`, the immutable
entry-order expiry boundary set by the first-fill transition (`null` in
`ema_anchor`).

#### Scenario: Preserve one singular desired entry
- **WHEN** a frozen executed entry context is constructed
- **THEN** it contains one complete `DesiredEntry` under `desired_entry`
- **AND** `CurrentTradeCycle` does not duplicate that desired entry as
  another field outside `applied_entry_package`/`frozen_entry_context`

#### Scenario: Reject invalid context fields
- **WHEN** `desired_entry` has the wrong type, `first_fill_at_ms` is not a
  strictly positive integer, `entry_bar_open_time_ms` is not a
  non-negative integer, `entry_order_expires_at_bar` is neither `null` nor a
  non-negative integer, or `entry_bar_open_time_ms > first_fill_at_ms`
- **THEN** context construction fails before the value can enter aggregate
  or repository state

#### Scenario: Keep price, quantity, and phase out of the frozen context
- **WHEN** a frozen executed entry context is constructed
- **THEN** it contains no average execution price, filled quantity,
  remaining quantity, fill ledger entry, execution phase, or any
  execution-lifecycle state
- **AND** it contains exactly the four required fields: `desired_entry`,
  `first_fill_at_ms`, `entry_bar_open_time_ms`, `entry_order_expires_at_bar`
