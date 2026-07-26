## ADDED Requirements

### Requirement: Reconciliation compares only singular desired-entry state
Runtime SHALL derive entry reconciliation only from the new
`DesiredEntry | null` and the currently acknowledged
`AppliedEntryPackage.applied_desired_entry | null`.

#### Scenario: Read the acknowledged desired entry
- **WHEN** a current cycle and its applied package exist
- **THEN** reconciliation uses only
  `current_trade_cycle.applied_entry_package.applied_desired_entry` as the
  currently applied desired entry
- **AND** does not use `desired_entry_frozen` as independent persisted state

#### Scenario: Represent no acknowledged desired entry
- **WHEN** `current_trade_cycle` is null
- **THEN** reconciliation treats the currently applied desired entry as null
- **AND** no valid non-null current cycle can have an absent applied package
- **AND** makes no claim about external order or position existence

### Requirement: Desired-entry equivalence is exact complete domain-value equivalence
Runtime SHALL consider two already-constructed immutable `DesiredEntry` values
equivalent if and only if all six domain fields are equal.

#### Scenario: Match complete equal values
- **WHEN** both values have equal `side`, `source_plan_bar_open_time_ms`,
  `planned_entry_price`, `initial_stop_price`, `initial_take_price`, and
  `locked_exit_profile`
- **THEN** they are equivalent

#### Scenario: Detect any field difference
- **WHEN** exactly one of `side`, `source_plan_bar_open_time_ms`,
  `planned_entry_price`, `initial_stop_price`, `initial_take_price`, or
  `locked_exit_profile` differs
- **THEN** the values are not equivalent

#### Scenario: Use canonical domain values
- **WHEN** reconciliation compares two valid `DesiredEntry` values
- **THEN** it performs no price-tolerance comparison, partial comparison,
  side arbitration, or additional decimal normalization
- **AND** relies on the canonical values established by `DesiredEntry`
  construction

### Requirement: Reconciliation produces the complete four-way decision table
Runtime SHALL produce exactly one closed payload-bearing decision variant from
`NoOp`, `Apply`, `Replace`, and `Cancel`.

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
- **AND** carries the new desired entry
- **AND** carries the acknowledged current `trade_cycle_id`

#### Scenario: Applied desired entry became absent
- **WHEN** the new desired entry is null
- **AND** an acknowledged applied package exists
- **THEN** the decision is `Cancel`
- **AND** carries the acknowledged current `trade_cycle_id`

### Requirement: I3 command models contain only reconciliation command data
Runtime SHALL define the transport-free `EntryReconciliationCommand` with
exactly `strategy_instance_id`, `trade_cycle_id`, `ticker`, and
`desired_entry: DesiredEntry | null`.

#### Scenario: Represent a present package command
- **WHEN** an `Apply` or `Replace` command is constructed
- **THEN** `desired_entry` is the canonical domain value carried by the
  decision
- **AND** no client request or wire DTO is constructed

#### Scenario: Represent an absent package command
- **WHEN** a `Cancel` command is constructed
- **THEN** `desired_entry` is null
- **AND** no client request or wire DTO is constructed

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

#### Scenario: Build a replace command
- **WHEN** the decision is `Replace` carrying a desired entry and cycle identity
- **AND** `apply_trade_cycle_id` is null
- **AND** the decision cycle identity equals the acknowledged current cycle
- **THEN** the command carries the decision desired entry unchanged
- **AND** uses the decision cycle identity
- **AND** copies the state strategy-instance identity and registered instrument

#### Scenario: Build a cancel command
- **WHEN** the decision is `Cancel` carrying a cycle identity
- **AND** `apply_trade_cycle_id` is null
- **AND** the decision cycle identity equals the acknowledged current cycle
- **THEN** the command contains `desired_entry: null`
- **AND** uses the decision cycle identity
- **AND** copies the state strategy-instance identity and registered instrument

#### Scenario: Fail explicitly for an incoherent required command
- **WHEN** `Apply` lacks a valid apply-only cycle identity, `NoOp`, `Replace`,
  or `Cancel` receives an apply-only identity, or a decision contradicts its
  required source state
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
- **WHEN** construction of an `Apply`, `Replace`, or `Cancel` command fails
- **THEN** Runtime constructs no alternative cancel, apply, replace, or no-op
  result
- **AND** I3 performs no immediate retry

#### Scenario: Leave the next bar on the ordinary path
- **WHEN** required command construction raises
  `EntryReconciliationInvariantError`
- **THEN** I3 stores no pending, suppression, fallback, or retry state
- **AND** a later closed bar remains eligible to derive reconciliation again
  through the ordinary pipeline

### Requirement: I3 success confirmations contain only transition facts
Runtime SHALL define the closed confirmation union
`EntryAppliedConfirmation | EntryAbsentConfirmation`.

#### Scenario: Represent an applied confirmation
- **WHEN** a successful present-package result is adapted for I3
- **THEN** `EntryAppliedConfirmation` contains exactly
  `strategy_instance_id`, `trade_cycle_id`, canonical
  `applied_desired_entry`, and finite exact-decimal `calculated_quantity`

#### Scenario: Represent an absent confirmation
- **WHEN** a successful absent-package result is adapted for I3
- **THEN** `EntryAbsentConfirmation` contains exactly
  `strategy_instance_id` and `trade_cycle_id`

#### Scenario: Keep transport adaptation outside I3
- **WHEN** either confirmation is constructed
- **THEN** I3 does not decode a response, inspect a response envelope, or
  invoke a client

### Requirement: The state applier accepts only successful confirmations
Runtime SHALL expose a pure state applier whose confirmation input is only
`EntryAppliedConfirmation | EntryAbsentConfirmation` and SHALL NOT make public
client or transport outcomes part of that input.

#### Scenario: Apply uses only applied confirmation
- **WHEN** the decision variant is `Apply`
- **THEN** only `EntryAppliedConfirmation` is action-compatible

#### Scenario: Replace uses only applied confirmation
- **WHEN** the decision variant is `Replace`
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
- **THEN** no successful I3 confirmation exists
- **AND** the I3 state applier is not invoked
- **AND** I3 defines no null confirmation or unconfirmed-result variant

### Requirement: Successful confirmations are checked fail-closed
Runtime SHALL validate every supplied successful confirmation against the
decision variant, originating command, ownership identities, decision desired
entry, and source-state preconditions before constructing replacement state.

#### Scenario: Accept matching applied confirmation
- **WHEN** `Apply` or `Replace` receives `EntryAppliedConfirmation`
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
- **WHEN** `Apply` or `Replace` receives `EntryAbsentConfirmation`, or
  `Cancel` receives `EntryAppliedConfirmation`
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
- **WHEN** source state does not satisfy the supplied `Apply`, `Replace`, or
  `Cancel` variant's preconditions
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** no partial state is constructed or retained

#### Scenario: Preserve value without constraining object identity
- **WHEN** a pure reconciliation component produces `NoOp` or raises
  `EntryReconciliationInvariantError`
- **THEN** the input aggregate remains unmodified and domain-value-equivalent
  to its pre-call snapshot
- **AND** no state transition is available for repository save
- **AND** Runtime imposes no requirement that any returned aggregate or nested
  value has the same Python object identity as an input value

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

#### Scenario: Replace retains cycle identity
- **WHEN** a valid `Replace` confirmation is applied
- **AND** source `current_trade_cycle` contains its required applied package
- **THEN** Runtime retains the existing `trade_cycle_id`
- **AND** atomically replaces the complete `AppliedEntryPackage`
- **AND** stores the confirmed desired entry and exact `calculated_quantity`

#### Scenario: Cancel clears the complete cycle
- **WHEN** a valid `Cancel` confirmation is applied
- **AND** source `current_trade_cycle` contains its required applied package
- **THEN** Runtime sets `current_trade_cycle` to null
- **AND** does not retain an empty cycle

### Requirement: Pure reconciliation has no orchestration or external dependencies
The I3 reconciliation, command-building, and success-transition components
SHALL remain free of external calls and production-flow dependencies.

#### Scenario: Execute all pure components
- **WHEN** decision, command construction, or successful confirmation
  application executes
- **THEN** it performs no HTTP, ABI-port, repository, mutex, Engine, position
  lookup, handoff, orchestrator, bootstrap, or infrastructure operation
- **AND** it neither imports nor constructs ABI request or response models

#### Scenario: Generate no identity
- **WHEN** command construction or confirmation application executes
- **THEN** it does not invoke `TradeCycleIdFactory`
- **AND** uses only the caller-reserved apply identity or the existing cycle
  identity carried by `Replace` or `Cancel`
