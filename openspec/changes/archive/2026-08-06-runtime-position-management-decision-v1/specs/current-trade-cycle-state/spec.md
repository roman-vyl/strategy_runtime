## MODIFIED Requirements

### Requirement: Current trade cycle has only the minimal I2 fields
`CurrentTradeCycle` SHALL contain exactly one non-empty `trade_cycle_id`, one
required `applied_entry_package: AppliedEntryPackage`, one nullable
`frozen_entry_context: FrozenExecutedEntryContext | null`, and one nullable
latest confirmed management protection:
`latest_confirmed_management_protection: DesiredProtection | null`. Null
means Runtime has not yet acknowledged any post-entry management change;
the initial protection remains available from
`frozen_entry_context.desired_entry` regardless. Runtime SHALL store only
this single latest confirmed value, never a history.

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
