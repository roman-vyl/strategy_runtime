# position-management-decision Specification

## Purpose

Define the pure decision boundary that turns an already-received
`PositionManagementRecipe` and the current trade cycle's acknowledged
protection into exactly one execution decision, with fail-closed invariant
handling.

## Requirements

### Requirement: Select one position-management decision
Runtime SHALL select exactly one closed decision variant from `NoOp`,
`ApplyProtection`, and `ClosePosition`, given a `PositionManagementRecipe`
and the current trade cycle's effective acknowledged protection.
`close_signal.active = true` SHALL take unconditional priority regardless
of protection equality, and `diagnostics` SHALL NOT influence the
decision.

#### Scenario: Active close always wins, regardless of protection
- **WHEN** `close_signal.active` is `true`, whether `desired_protection`
  equals or differs from the effective acknowledged protection
- **THEN** the decision is `ClosePosition`, carrying the trade cycle's
  `trade_cycle_id` and the recipe's `close_signal`
- **AND** no `ApplyProtection` decision is produced for that recipe

#### Scenario: Equal protection is a no-op
- **WHEN** `close_signal.active` is `false` and `desired_protection` equals
  the effective acknowledged protection
- **THEN** the decision is `NoOp`, carrying no execution payload

#### Scenario: Different protection applies the change
- **WHEN** `close_signal.active` is `false` and `desired_protection`
  differs from the effective acknowledged protection
- **THEN** the decision is `ApplyProtection`, carrying the trade cycle's
  `trade_cycle_id` and `desired_protection`

#### Scenario: Diagnostics do not affect the decision
- **WHEN** two recipes share equal `close_signal` and `desired_protection`
  but different `diagnostics`
- **THEN** both select the identical decision variant and payload

### Requirement: Resolve effective acknowledged protection
Runtime SHALL resolve the effective acknowledged protection from exactly
two sources, in order: the current trade cycle's latest confirmed
management protection if set; otherwise the initial protection implied by
`frozen_entry_context.desired_entry`'s stop/take.

#### Scenario: Initial frozen protection is the baseline
- **WHEN** the current trade cycle's latest confirmed management
  protection is null
- **THEN** the effective acknowledged protection is built from
  `frozen_entry_context.desired_entry`'s `initial_stop_price` and
  `initial_take_price`

#### Scenario: Latest confirmed protection supersedes the baseline
- **WHEN** the current trade cycle's latest confirmed management
  protection is not null
- **THEN** the effective acknowledged protection is that value
- **AND** the frozen entry context's initial stop/take is not read

### Requirement: Fail closed for invalid lifecycle state
Runtime SHALL raise a typed invariant error, and SHALL NOT select a
decision, when the current trade cycle is missing, its entry is not yet
frozen, or an input has the wrong type.

#### Scenario: Missing current trade cycle fails closed
- **WHEN** `current_trade_cycle` is null
- **THEN** the decision boundary raises the typed invariant error
- **AND** no decision is produced

#### Scenario: Unfrozen current trade cycle fails closed
- **WHEN** `current_trade_cycle` exists but `frozen_entry_context` is null
- **THEN** the decision boundary raises the typed invariant error
