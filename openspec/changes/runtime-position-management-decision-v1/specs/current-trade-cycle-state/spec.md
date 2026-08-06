## ADDED Requirements

### Requirement: Current trade cycle may hold the latest confirmed management protection
`CurrentTradeCycle` SHALL carry a nullable latest confirmed management
protection, distinct from `frozen_entry_context`'s initial stop/take. Null
means Runtime has not yet acknowledged any post-entry management change;
the initial protection remains available from `frozen_entry_context`
regardless. Runtime SHALL NOT store a protection history, a pending
execution state, or diagnostics alongside it.

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
