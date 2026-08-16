## MODIFIED Requirements

### Requirement: Reconciliation produces the complete three-way decision table
Runtime SHALL produce exactly one closed payload-bearing decision variant from
`NoOp`, `Apply`, and `Cancel`. `Replace` no longer exists as a decision
variant: any change to the acknowledged applied desired entry decides
`Cancel`, identically to the applied desired entry becoming absent, because
physical replace is served exclusively by cancellation (see
`current-trade-cycle-state` and the paired ABI capability
`entry-package-execution`).

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
- **THEN** the decision is `Cancel`
- **AND** carries the acknowledged current `trade_cycle_id`
- **AND** does not carry the new desired entry — it is discarded at the
  decision level; a later bar's fresh reconciliation is the only path by
  which any new desired entry is ever applied

#### Scenario: Applied desired entry became absent
- **WHEN** the new desired entry is null
- **AND** an acknowledged applied package exists
- **THEN** the decision is `Cancel`
- **AND** carries the acknowledged current `trade_cycle_id`

### Requirement: Command construction distinguishes no-op from invariant failure
Runtime SHALL construct `EntryReconciliationCommand` purely from the
payload-bearing decision, aggregate state, and optional
`apply_trade_cycle_id`, and SHALL represent command absence as successful only
for a valid `NoOp`.

#### Scenario: Build no command for no-op
- **WHEN** the decision is `NoOp`
- **AND** `apply_trade_cycle_id` is null
- **THEN** command construction returns null as a successful no-command result
- **AND** requires no external call or confirmation

#### Scenario: Build an apply command
- **WHEN** the decision is `Apply` carrying a desired entry
- **AND** a non-empty caller-reserved `apply_trade_cycle_id` is supplied
- **AND** source `current_trade_cycle` is null
- **THEN** the command carries the decision desired entry unchanged
- **AND** copies `state.strategy_instance_id`
- **AND** copies `state.registered_spec_snapshot.instrument` as ticker
- **AND** uses the supplied apply cycle identity without generating one

#### Scenario: Build a cancel command
- **WHEN** the decision is `Cancel` carrying a cycle identity
- **AND** `apply_trade_cycle_id` is null
- **AND** the decision cycle identity equals the acknowledged current cycle
- **THEN** the command contains `desired_entry: null`
- **AND** uses the decision cycle identity
- **AND** copies the state strategy-instance identity and registered instrument
- **AND** this holds identically whether `Cancel` arose from a null new
  desired entry or from a changed one — the command never carries a changed
  desired entry

#### Scenario: Fail explicitly for an incoherent required command
- **WHEN** `Apply` lacks a valid apply-only cycle identity, `NoOp` or `Cancel`
  receives an apply-only identity, or a decision contradicts its required
  source state
- **THEN** command construction raises
  `EntryReconciliationInvariantError`
- **AND** returns neither null nor an `EntryReconciliationCommand`
- **AND** performs no external call or state mutation

#### Scenario: Do not duplicate reconciliation inputs
- **WHEN** command construction receives a payload-bearing decision
- **THEN** it receives no separate new desired entry or generic target-cycle
  identity
- **AND** it does not repeat desired-entry reconciliation

#### Scenario: Produce no fallback action
- **WHEN** construction of an `Apply` or `Cancel` command fails
- **THEN** Runtime constructs no alternative cancel, apply, or no-op result
- **AND** Runtime performs no immediate retry

#### Scenario: Leave the next bar on the ordinary path
- **WHEN** required command construction raises
  `EntryReconciliationInvariantError`
- **THEN** Runtime stores no pending, suppression, fallback, or retry state
  in this pure component — the durable `pending_entry_recovery` marker
  (`pending-entry-recovery-state`) is a distinct, application-level concern
  owned by `entry-reconciliation-orchestrator`, not by this invariant-failure
  path
- **AND** a later closed bar remains eligible to derive reconciliation again
  through the ordinary pipeline

### Requirement: The state applier accepts only successful confirmations
Runtime SHALL expose a pure state applier whose confirmation input is only
`EntryAppliedConfirmation | EntryAbsentConfirmation` and SHALL NOT make public
client or transport outcomes part of that input.

#### Scenario: Apply uses only applied confirmation
- **WHEN** the decision variant is `Apply`
- **THEN** only `EntryAppliedConfirmation` is action-compatible

#### Scenario: Cancel uses only absent confirmation
- **WHEN** the decision variant is `Cancel`
- **THEN** only `EntryAbsentConfirmation` is action-compatible

#### Scenario: No-op bypasses confirmation application
- **WHEN** reconciliation produces `NoOp`
- **THEN** no command is sent
- **AND** the successful confirmation applier is not invoked

#### Scenario: Exclude non-success client outcomes
- **WHEN** a client returns a public error or raises timeout, network, or
  protocol failure
- **THEN** no successful confirmation exists
- **AND** the state applier is not invoked
- **AND** reconciliation defines no null confirmation or unconfirmed-result variant

### Requirement: Successful confirmations are checked fail-closed
Runtime SHALL validate every supplied successful confirmation against the
decision variant, originating command, ownership identities, decision desired
entry, and source-state preconditions before constructing replacement state.

#### Scenario: Accept matching applied confirmation
- **WHEN** `Apply` receives `EntryAppliedConfirmation`
- **AND** its strategy-instance and trade-cycle identities match the aggregate,
  decision, and sent command
- **AND** its desired entry is exactly domain-equivalent to the desired entry
  carried by the decision and sent in the command
- **AND** source state satisfies the decision variant
- **THEN** the confirmation is eligible for transition

#### Scenario: Accept matching absent confirmation
- **WHEN** `Cancel` receives `EntryAbsentConfirmation`
- **AND** its strategy-instance and trade-cycle identities match the aggregate,
  decision, sent command, and acknowledged current cycle
- **AND** `sent_command.desired_entry` is null
- **AND** source state satisfies cancellation preconditions
- **THEN** the confirmation is eligible for transition

#### Scenario: Reject a present package in a cancel command
- **WHEN** the decision is `Cancel`
- **AND** `sent_command.desired_entry` is non-null
- **AND** the confirmation is `EntryAbsentConfirmation`
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot

#### Scenario: Reject a wrong success variant
- **WHEN** `Apply` receives `EntryAbsentConfirmation`, or `Cancel` receives
  `EntryAppliedConfirmation`
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot

#### Scenario: Reject strategy-instance mismatch
- **WHEN** a successful confirmation has another `strategy_instance_id`
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot

#### Scenario: Reject trade-cycle mismatch
- **WHEN** a successful confirmation has another `trade_cycle_id`
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot

#### Scenario: Reject applied-entry mismatch
- **WHEN** an applied confirmation's desired entry is not exactly
  domain-equivalent to the desired entry carried by the decision and sent in
  the command
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** no confirmation quantity is stored
- **AND** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot

#### Scenario: Reject invalid confirmation quantity
- **WHEN** an applied confirmation has a calculated quantity outside the
  finite exact-decimal invariant
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** no partial state is constructed or retained

#### Scenario: Reject incoherent source state
- **WHEN** source state does not satisfy the supplied `Apply` or `Cancel`
  variant's preconditions
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** no partial state is constructed or retained

#### Scenario: Preserve value without constraining object identity
- **WHEN** a pure reconciliation component produces `NoOp` or raises
  `EntryReconciliationInvariantError`
- **THEN** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot
- **AND** no state transition is available for repository save
- **AND** Runtime requires value preservation, not preservation of a particular
  in-memory aggregate or nested-value instance

### Requirement: Successful confirmations produce the closed state-transition table
Runtime SHALL produce a new complete immutable aggregate only for a successful
confirmation that passes every invariant check.

#### Scenario: Apply creates an acknowledged cycle
- **WHEN** a valid `Apply` confirmation is applied
- **AND** source `current_trade_cycle` is null
- **THEN** Runtime creates one `CurrentTradeCycle` with the confirmed target
  identity
- **AND** stores the confirmed desired entry and exact
  `calculated_quantity`

#### Scenario: Cancel clears the complete cycle
- **WHEN** a valid `Cancel` confirmation is applied
- **AND** source `current_trade_cycle` contains its required applied package
- **THEN** Runtime sets `current_trade_cycle` to null
- **AND** does not retain an empty cycle
- **AND** this holds identically whether the `Cancel` decision arose from a
  null new desired entry or from a changed one — no variant of `Cancel`
  retains or replaces the prior `AppliedEntryPackage`

### Requirement: Reconciliation fails closed once the entry context is frozen
`decide_entry_reconciliation(new_desired_entry, current_trade_cycle)` SHALL
raise `EntryReconciliationInvariantError` before evaluating the three-way
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
- **AND** it does not return `Cancel`

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
