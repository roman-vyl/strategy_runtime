## MODIFIED Requirements

### Requirement: Cancel reuses decision-owned identity
The orchestrator SHALL construct `Cancel` commands without reserving a new
trade-cycle identity. `Replace` no longer exists as a decision variant (see
`entry-reconciliation`); every non-`Apply` command-bearing decision is now
`Cancel`.

#### Scenario: Build Cancel from its decision
- **WHEN** pure reconciliation returns `Cancel`
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory`
- **AND** invokes the existing command builder without an apply-only identity
- **AND** the builder uses the `trade_cycle_id` carried by the decision

### Requirement: Every command-bearing decision executes exactly once
The orchestrator SHALL send the one command built for `Apply` or `Cancel`
together with the exact extracted `source_state` to its injected execution
port exactly once.

#### Scenario: Execute one Apply command
- **WHEN** the existing builder successfully constructs an `Apply` command
- **THEN** the execution port is invoked exactly once with that exact command
  and exact extracted `source_state`

#### Scenario: Execute one Cancel command
- **WHEN** the existing builder successfully constructs a `Cancel` command
- **THEN** the execution port is invoked exactly once with that exact command
  and exact extracted `source_state`

#### Scenario: Do not retry execution
- **WHEN** the execution port raises an exception
- **THEN** the orchestrator does not invoke the port again
- **AND** does not construct or execute a fallback command

### Requirement: Confirmed command-bearing decisions return replacement state
The orchestrator SHALL return only the complete replacement aggregate produced
by the existing successful-confirmation applier for `Apply` or `Cancel`.

#### Scenario: Return confirmed Apply replacement
- **WHEN** a valid `Apply` command receives and applies its matching
  `EntryAppliedConfirmation`
- **THEN** the result is a replacement aggregate containing the newly
  acknowledged current cycle
- **AND** the extracted `source_state` remains unmodified

#### Scenario: Return confirmed Cancel replacement
- **WHEN** a valid `Cancel` command receives and applies its matching
  `EntryAbsentConfirmation`
- **THEN** the result is a replacement aggregate with
  `current_trade_cycle = null`
- **AND** the extracted `source_state` remains unmodified

### Requirement: External failure preserves source state and propagates
The orchestrator SHALL propagate every execution-boundary exception to its
caller without a state transition.

#### Scenario: Propagate execution failure
- **WHEN** external execution raises an exception for `Apply` or `Cancel`
- **THEN** the same failure propagates to the caller
- **AND** the extracted `source_state` remains unmodified and
  domain-value-equivalent to its pre-call snapshot, except for the durable
  `pending_entry_recovery` marker already saved before the execution port was
  invoked (see "Durable recovery marker is saved before every entry mutation
  side effect")
- **AND** no replacement aggregate, confirmation application, retry, fallback,
  or local intermediate state is produced

#### Scenario: Discard an unacknowledged Apply reservation
- **WHEN** `Apply` reserved an identity and external execution then fails
- **THEN** that reservation creates no acknowledged cycle
- **AND** the durable `pending_entry_recovery` marker for that identity
  remains set, precisely so the identity itself is not discarded
- **AND** a later caller remains free to enter the ordinary reconciliation
  path once `pending_entry_recovery` is resolved

## ADDED Requirements

### Requirement: Durable recovery marker is saved before every entry mutation side effect
Before invoking the execution port for `Apply` or `Cancel`, the orchestrator
SHALL durably save `pending_entry_recovery = {trade_cycle_id}` on the source
state, using the same `trade_cycle_id` the command carries (the freshly
reserved identity for `Apply`, the existing current-cycle identity for
`Cancel`). This save SHALL complete before any request reaches ABI. The
marker carries no timestamp — it records only which trade cycle is uncertain,
not when the uncertainty began.

#### Scenario: Marker precedes the Apply side effect
- **WHEN** the orchestrator is about to invoke the execution port for a valid
  `Apply` command
- **THEN** it first durably saves `pending_entry_recovery` with the reserved
  `apply_trade_cycle_id`
- **AND** only then invokes the execution port

#### Scenario: Marker precedes the Cancel side effect
- **WHEN** the orchestrator is about to invoke the execution port for a valid
  `Cancel` command
- **THEN** it first durably saves `pending_entry_recovery` with the acknowledged
  current cycle's `trade_cycle_id`
- **AND** only then invokes the execution port

#### Scenario: A successful confirmation clears the marker in the same transition
- **WHEN** a successful confirmation is applied for `Apply` or `Cancel`
- **THEN** the resulting replacement aggregate has `pending_entry_recovery =
  null`
- **AND** the confirmed `current_trade_cycle` transition and the marker
  clearing are part of the same durable save

#### Scenario: An execution failure leaves the marker exactly as saved
- **WHEN** the execution port raises after the marker was durably saved
- **THEN** the orchestrator performs no further save for this invocation
- **AND** `pending_entry_recovery` remains exactly as durably saved,
  available for `uncertain-exchange-state-resolver` to resolve later
