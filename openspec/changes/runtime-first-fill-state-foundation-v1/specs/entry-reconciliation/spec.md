## ADDED Requirements

### Requirement: Reconciliation fails closed once the entry context is frozen
`decide_entry_reconciliation(new_desired_entry, current_trade_cycle)` SHALL
raise `EntryReconciliationInvariantError` before evaluating the four-way
decision table when `current_trade_cycle` is not null and
`current_trade_cycle.frozen_entry_context` is not null. This check runs
before any desired-entry equivalence comparison, so no `EntryReconciliationCommand`
is built and `EntryReconciliationExecutionPort.execute` is never invoked once
a trade cycle's entry context is frozen.

#### Scenario: Reject an identical desired entry once frozen
- **WHEN** `current_trade_cycle.frozen_entry_context` is not null
- **AND** `new_desired_entry` is equivalent to the acknowledged applied
  desired entry
- **THEN** `decide_entry_reconciliation` raises
  `EntryReconciliationInvariantError`
- **AND** it does not return `NoOp`

#### Scenario: Reject a changed desired entry once frozen
- **WHEN** `current_trade_cycle.frozen_entry_context` is not null
- **AND** `new_desired_entry` is non-null and not equivalent to the
  acknowledged applied desired entry
- **THEN** `decide_entry_reconciliation` raises
  `EntryReconciliationInvariantError`
- **AND** it does not return `Replace`

#### Scenario: Reject a null desired entry once frozen
- **WHEN** `current_trade_cycle.frozen_entry_context` is not null
- **AND** `new_desired_entry` is null
- **THEN** `decide_entry_reconciliation` raises
  `EntryReconciliationInvariantError`
- **AND** it does not return `Cancel`

#### Scenario: No command is built and no execution port call happens
- **WHEN** `decide_entry_reconciliation` raises
  `EntryReconciliationInvariantError` because the entry context is frozen
- **THEN** `build_entry_reconciliation_command` is never called
- **AND** `EntryReconciliationExecutionPort.execute` is never called
- **AND** no ABI entry-package command is sent
- **AND** the source `StrategyInstanceRuntimeState` remains unmodified
