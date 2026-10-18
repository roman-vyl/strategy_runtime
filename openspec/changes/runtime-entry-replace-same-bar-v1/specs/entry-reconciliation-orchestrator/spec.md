## ADDED Requirements

### Requirement: Changed entry is replaced in the same bar after confirmed absence
When pure reconciliation returns `Cancel` and `projection.desired_entry` is not
null, the orchestrator SHALL, after the cancel's `EntryAbsentConfirmation` has
been applied, apply `projection.desired_entry` in the same invocation as a new
trade cycle with a freshly reserved `trade_cycle_id`. It SHALL do so only after
a confirmed absence, through a second, independent execution-port call, and
SHALL make at most two execution-port calls per invocation, cancel first, then
apply. The ABI contract is unchanged: ABI still serves a changed entry as
cancel-only, and the follow-up is an ordinary apply for a trade cycle with no
existing binding.

#### Scenario: Cancel then apply in one invocation
- **WHEN** the acknowledged pending cycle's desired entry differs from a
  non-null `projection.desired_entry`
- **AND** the cancel's execution-port call returns a matching
  `EntryAbsentConfirmation`
- **THEN** the orchestrator applies that confirmation to obtain an absent state
  with `current_trade_cycle = null`
- **AND** re-decides with `projection.desired_entry` against that absent state,
  which yields `Apply`
- **AND** invokes `TradeCycleIdFactory` exactly once for the follow-up
- **AND** invokes the execution port a second time with the follow-up `Apply`
  command and the absent state
- **AND** returns the replacement aggregate whose current cycle carries the new
  `trade_cycle_id`

#### Scenario: Absent state is durable before the follow-up request
- **WHEN** the follow-up `Apply` command has been built
- **THEN** the orchestrator durably saves the absent state with
  `pending_entry_recovery = {new trade_cycle_id}` in one save
- **AND** that save completes before the follow-up request reaches ABI
- **AND** no durable state exists in which the old cycle is still acknowledged
  after the follow-up request was sent

#### Scenario: Journal only the new cycle
- **WHEN** the follow-up returns `EntryAppliedConfirmation`
- **THEN** the orchestrator writes exactly one `entry_package_applied` event,
  for the new trade cycle and the processing bar
- **AND** writes no event for the cancel and no new event type

#### Scenario: Cancel failure places no new order
- **WHEN** the cancel's execution-port call raises, including a Runtime timeout,
  an ambiguous or unknown result, or ABI reporting a fill before cancel
- **THEN** the exception propagates
- **AND** no follow-up identity is reserved and no second execution-port call is
  made
- **AND** `pending_entry_recovery` remains on the old cycle for the existing
  recovery and open-position paths

#### Scenario: Follow-up failure goes to existing recovery
- **WHEN** the follow-up execution-port call raises
- **THEN** the exception propagates without retry or a third execution-port call
- **AND** the durable state is the absent state with
  `pending_entry_recovery = {new trade_cycle_id}`

#### Scenario: Null desired entry stays cancel-only
- **WHEN** pure reconciliation returns `Cancel` because `projection.desired_entry`
  is null
- **THEN** the orchestrator executes only the cancel
- **AND** reserves no identity and makes no second execution-port call

## MODIFIED Requirements

### Requirement: Orchestrator accepts only one live-entry projection
Runtime SHALL expose
`EntryReconciliationOrchestrator.execute(projection)` whose only operation
input is one `LiveEntryProjectedStrategyInstance` and whose output is a
`StrategyInstanceRuntimeState`.

#### Scenario: Extract the exact source state
- **WHEN** the operation receives a valid live-entry projection
- **THEN** it sets `source_state` to the exact
  `projection.source.resolved_state.runtime_state` snapshot
- **AND** does not accept, load, or derive a second Runtime-state input
- **AND** does not copy that state into a new application input DTO

#### Scenario: Use one snapshot throughout the operation
- **WHEN** the operation has extracted `source_state`
- **THEN** it passes `projection.desired_entry` and
  `source_state.current_trade_cycle` to the existing pure reconciliation
  decision
- **AND** uses that exact `source_state` for command construction
- **AND** passes that exact `source_state` to the execution port
- **AND** uses that exact `source_state` as the aggregate supplied to any
  successful-confirmation application
- **AND** the only exception is the same-bar follow-up `Apply` (see "Changed
  entry is replaced in the same bar after confirmed absence"), which uses the
  absent state produced from that snapshot by the confirmed cancel

#### Scenario: Add no redundant state binding check
- **WHEN** the operation uses the projection's embedded Runtime state
- **THEN** it performs no binding check against another independently supplied
  state
- **AND** no second state argument exists in its public contract

#### Scenario: Return only aggregate state
- **WHEN** the operation completes successfully
- **THEN** it returns either logically unchanged aggregate state or one
  complete replacement aggregate
- **AND** does not return a decision, command, confirmation, transport result,
  repository instruction, or partial transition wrapper

### Requirement: Cancel reuses decision-owned identity
The orchestrator SHALL construct `Cancel` commands without reserving a new
trade-cycle identity. `Replace` no longer exists as a decision variant (see
`entry-reconciliation`); every non-`Apply` command-bearing decision is now
`Cancel`. A same-bar follow-up `Apply` after a confirmed changed-entry cancel
is a separate decision and reserves its own identity.

#### Scenario: Build Cancel from its decision
- **WHEN** pure reconciliation returns `Cancel`
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory` to build the
  cancel command
- **AND** invokes the existing command builder without an apply-only identity
- **AND** the builder uses the `trade_cycle_id` carried by the decision

### Requirement: Every command-bearing decision executes exactly once
The orchestrator SHALL send each command built for `Apply` or `Cancel`
together with the state it was built against to its injected execution port
exactly once. An invocation SHALL build at most two commands: the decided
command, and, only after a confirmed changed-entry cancel, one follow-up
`Apply`.

#### Scenario: Execute one Apply command
- **WHEN** the existing builder successfully constructs an `Apply` command
- **THEN** the execution port is invoked exactly once with that exact command
  and exact extracted `source_state`

#### Scenario: Execute one Cancel command
- **WHEN** the existing builder successfully constructs a `Cancel` command
- **THEN** the execution port is invoked exactly once with that exact command
  and exact extracted `source_state`

#### Scenario: Execute one follow-up Apply command
- **WHEN** a changed-entry cancel was confirmed absent and the follow-up
  `Apply` command was built
- **THEN** the execution port is invoked exactly once with that follow-up
  command and the absent state
- **AND** only after the cancel's execution-port call returned

#### Scenario: Do not retry execution
- **WHEN** the execution port raises an exception
- **THEN** the orchestrator does not invoke the port again
- **AND** does not construct or execute a fallback command

### Requirement: Confirmed command-bearing decisions return replacement state
The orchestrator SHALL return only the complete replacement aggregate produced
by the existing successful-confirmation applier for `Apply` or `Cancel`, or,
for a confirmed changed-entry cancel, the replacement produced for the
follow-up `Apply`.

#### Scenario: Return confirmed Apply replacement
- **WHEN** a valid `Apply` command receives and applies its matching
  `EntryAppliedConfirmation`
- **THEN** the result is a replacement aggregate containing the newly
  acknowledged current cycle
- **AND** the extracted `source_state` remains unmodified

#### Scenario: Return confirmed Cancel replacement
- **WHEN** a valid `Cancel` command for a null `projection.desired_entry`
  receives and applies its matching `EntryAbsentConfirmation`
- **THEN** the result is a replacement aggregate with
  `current_trade_cycle = null`
- **AND** the extracted `source_state` remains unmodified

#### Scenario: Return confirmed replace replacement
- **WHEN** a changed-entry `Cancel` is confirmed absent and the follow-up
  `Apply` receives and applies its matching `EntryAppliedConfirmation`
- **THEN** the result is a replacement aggregate whose current cycle carries
  the new `trade_cycle_id` and `projection.desired_entry`
- **AND** the extracted `source_state` remains unmodified

### Requirement: Durable recovery marker is saved before every entry mutation side effect
Before invoking the execution port for `Apply` or `Cancel`, the orchestrator
SHALL durably save `pending_entry_recovery = {trade_cycle_id}` on the state
the command was built against, using the same `trade_cycle_id` the command
carries (the freshly reserved identity for `Apply`, the existing current-cycle
identity for `Cancel`). For a same-bar follow-up `Apply` that state is the
absent state, so the cancel's result and the new marker become durable in one
save. This save SHALL complete before any request reaches ABI. The
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

#### Scenario: Marker precedes the follow-up Apply side effect
- **WHEN** the orchestrator is about to invoke the execution port for a
  same-bar follow-up `Apply` command
- **THEN** it first durably saves the absent state with
  `current_trade_cycle = null` and `pending_entry_recovery` set to the new
  `trade_cycle_id`
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

### Requirement: Nested operation owns no outer workflow or transport concern
The `EntryReconciliationOrchestrator` SHALL NOT acquire coordination, load
repository state, adapt transport models, or control another Runtime workflow.
Its only repository writes SHALL be the recovery-marker saves required by
"Durable recovery marker is saved before every entry mutation side effect".

#### Scenario: Leave closed-bar ownership to the outer orchestrator
- **WHEN** the operation runs
- **THEN** it does not acquire or release a keyed mutex
- **AND** does not call repository get or get-or-create
- **AND** calls repository save only for the pre-execution recovery-marker saves
- **AND** does not reload the state embedded in the projection
- **AND** does not invoke `StrategyRuntimeOrchestrator` or outer strategy-cycle dispatch

#### Scenario: Leave adapters and adjacent branches outside
- **WHEN** the operation runs
- **THEN** it performs no HTTP or ABI DTO/codec adaptation
- **AND** performs no Engine call or open-position lookup
- **AND** does not process the open-trade branch, fill webhook, or
  execution-event lifecycle
