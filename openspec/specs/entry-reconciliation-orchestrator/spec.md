# entry-reconciliation-orchestrator Specification

## Purpose

Define the nested Runtime application operation that composes pure desired-entry
reconciliation with apply-only identity reservation, transport-free external
execution, and confirmation-gated aggregate state replacement.

## Requirements

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

### Requirement: NoOp performs no command-bearing work
The orchestrator SHALL treat `NoOp` as a completed application operation with
no logical state transition.

#### Scenario: Bypass every side-effect boundary
- **WHEN** pure reconciliation returns `NoOp`
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory`
- **AND** does not invoke the command builder
- **AND** does not invoke the execution port
- **AND** does not invoke the successful-confirmation applier

#### Scenario: Preserve state value without object-identity constraints
- **WHEN** pure reconciliation returns `NoOp`
- **THEN** the result is domain-value-equivalent to the extracted `source_state`
- **AND** no logical state transition is available to the caller
- **AND** Runtime imposes no requirement that the returned aggregate or nested
  values have the same Python object identity as the extracted `source_state`

### Requirement: Apply reserves exactly one new trade-cycle identity
The orchestrator SHALL reserve an apply-only `trade_cycle_id` through its
injected `TradeCycleIdFactory` only after reconciliation produces `Apply`.

#### Scenario: Reserve and pass one Apply identity
- **WHEN** pure reconciliation returns `Apply`
- **THEN** the orchestrator invokes `TradeCycleIdFactory` exactly once
- **AND** supplies that exact returned identity as
  `apply_trade_cycle_id` to the existing command builder
- **AND** does not generate, derive, normalize, or replace the identity itself

#### Scenario: Do not acknowledge reservation before confirmation
- **WHEN** an `Apply` identity has been reserved but no valid successful
  confirmation has been applied
- **THEN** no `CurrentTradeCycle` is created
- **AND** the extracted `source_state` remains logically unchanged

### Requirement: Replace and Cancel reuse decision-owned identity
The orchestrator SHALL construct `Replace` and `Cancel` commands without
reserving a new trade-cycle identity.

#### Scenario: Build Replace from its decision
- **WHEN** pure reconciliation returns `Replace`
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory`
- **AND** invokes the existing command builder without an apply-only identity
- **AND** the builder uses the `trade_cycle_id` carried by the decision

#### Scenario: Build Cancel from its decision
- **WHEN** pure reconciliation returns `Cancel`
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory`
- **AND** invokes the existing command builder without an apply-only identity
- **AND** the builder uses the `trade_cycle_id` carried by the decision

### Requirement: Every command-bearing decision executes exactly once
The orchestrator SHALL send the one command built for `Apply`, `Replace`, or
`Cancel` together with the exact extracted `source_state` to its injected
execution port exactly once.

#### Scenario: Execute one Apply command
- **WHEN** the existing builder successfully constructs an `Apply` command
- **THEN** the execution port is invoked exactly once with that exact command
  and exact extracted `source_state`

#### Scenario: Execute one Replace command
- **WHEN** the existing builder successfully constructs a `Replace` command
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

### Requirement: Execution port is narrow and transport-free
Runtime SHALL define an injected `EntryReconciliationExecutionPort` owned by
the application capability with exactly one operation that accepts an existing
`EntryReconciliationCommand` plus the exact source
`StrategyInstanceRuntimeState` and returns an existing
`SuccessfulEntryConfirmation`:

```text
execute(
    command: EntryReconciliationCommand,
    source_state: StrategyInstanceRuntimeState,
) -> SuccessfulEntryConfirmation
```

#### Scenario: Pass command and source-state values
- **WHEN** the orchestrator invokes the execution port
- **THEN** the first argument is the existing transport-free
  `EntryReconciliationCommand`
- **AND** the second argument is the exact `source_state` extracted from the
  projection
- **AND** a normal return is exactly
  `EntryAppliedConfirmation | EntryAbsentConfirmation`

#### Scenario: Represent execution failure by exception
- **WHEN** external execution cannot produce a successful confirmation
- **THEN** the port raises an exception
- **AND** does not return null, false, a fabricated confirmation, a public
  error result, or a retry instruction

#### Scenario: Exclude transport contracts
- **WHEN** the execution port is defined or invoked
- **THEN** its contract contains no HTTP DTO, ABI request or response model,
  codec, response envelope, status code, timeout policy, or transport client

### Requirement: Only successful confirmation can trigger state application
The orchestrator SHALL invoke the existing successful-confirmation applier only
after external execution returns a value in the closed
`SuccessfulEntryConfirmation` union.

#### Scenario: Apply a successful confirmation
- **WHEN** one command has been executed
- **AND** the execution port returns
  `EntryAppliedConfirmation | EntryAbsentConfirmation`
- **THEN** the orchestrator invokes the existing applier exactly once with the
  exact extracted `source_state`, original decision, exact sent command, and
  returned confirmation

#### Scenario: Reject a non-success port result before application
- **WHEN** an execution-port implementation violates its contract by returning
  a value outside `SuccessfulEntryConfirmation`
- **THEN** the orchestrator raises `EntryReconciliationInvariantError`
- **AND** does not invoke the successful-confirmation applier
- **AND** does not construct replacement state

#### Scenario: Bypass application on execution exception
- **WHEN** the execution port raises an exception
- **THEN** the successful-confirmation applier is not invoked
- **AND** no replacement aggregate is returned

### Requirement: Confirmed command-bearing decisions return replacement state
The orchestrator SHALL return only the complete replacement aggregate produced
by the existing successful-confirmation applier for `Apply`, `Replace`, or
`Cancel`.

#### Scenario: Return confirmed Apply replacement
- **WHEN** a valid `Apply` command receives and applies its matching
  `EntryAppliedConfirmation`
- **THEN** the result is a replacement aggregate containing the newly
  acknowledged current cycle
- **AND** the extracted `source_state` remains unmodified

#### Scenario: Return confirmed Replace replacement
- **WHEN** a valid `Replace` command receives and applies its matching
  `EntryAppliedConfirmation`
- **THEN** the result is a replacement aggregate with the confirmed applied
  package and existing cycle identity
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
- **WHEN** external execution raises an exception for `Apply`, `Replace`, or
  `Cancel`
- **THEN** the same failure propagates to the caller
- **AND** the extracted `source_state` remains unmodified and
  domain-value-equivalent to its pre-call snapshot
- **AND** no replacement aggregate, confirmation application, retry, fallback,
  or local intermediate state is produced

#### Scenario: Discard an unacknowledged Apply reservation
- **WHEN** `Apply` reserved an identity and external execution then fails
- **THEN** that reservation creates no acknowledged cycle or retained pending
  state
- **AND** a later caller remains free to enter the ordinary reconciliation
  path

### Requirement: Invariant failures preserve source state and propagate
The orchestrator SHALL fail closed for every invariant failure raised during
decision handling, identity use, command construction, execution-result
validation, or successful-confirmation application.

#### Scenario: Propagate command invariant failure
- **WHEN** the existing command builder raises
  `EntryReconciliationInvariantError`
- **THEN** the error propagates to the caller
- **AND** the execution port and confirmation applier are not invoked
- **AND** the extracted `source_state` remains logically unchanged

#### Scenario: Propagate confirmation invariant failure
- **WHEN** the existing applier rejects a contradictory successful confirmation
- **THEN** `EntryReconciliationInvariantError` propagates to the caller
- **AND** the execution port is not invoked a second time
- **AND** no replacement aggregate is returned
- **AND** the extracted `source_state` remains unmodified and
  domain-value-equivalent to its pre-call snapshot

#### Scenario: Create no local recovery behavior
- **WHEN** any invariant failure occurs
- **THEN** the orchestrator creates no retry, fallback, pending action,
  suppression marker, partial aggregate, or alternative decision

### Requirement: Pure reconciliation remains independent of application orchestration
The dependency direction SHALL run from the new application package to the
existing pure `runtime/entry_reconciliation` package and never in reverse.

#### Scenario: Application composes approved pure dependencies
- **WHEN** the orchestrator decides, builds, and applies a confirmed transition
- **THEN** it uses the existing reconciliation decision, command builder, and
  successful-confirmation applier
- **AND** does not duplicate their comparison, command-field, or transition
  rules

#### Scenario: Pure modules do not know the application layer
- **WHEN** dependencies of `runtime/entry_reconciliation` are inspected
- **THEN** they contain no import of
  `entry_reconciliation_orchestrator`, its execution port, or another
  application orchestrator

#### Scenario: Constrain direct dependencies rather than transitive model graph
- **WHEN** direct imports and behavior of the new application package are
  inspected
- **THEN** it has no direct import of or behavioral dependency on
  open-position or open-trade application and adapter modules
- **AND** importing `LiveEntryProjectedStrategyInstance` from
  `runtime.routing.models` remains allowed
- **AND** existing transitive model imports of `runtime.routing.models` are not
  treated as direct dependencies of the new application package

### Requirement: Nested operation owns no outer workflow or transport concern
The `EntryReconciliationOrchestrator` SHALL NOT acquire coordination, load or
save repository state, adapt transport models, or control another Runtime
workflow.

#### Scenario: Leave closed-bar ownership to the future caller
- **WHEN** the operation runs
- **THEN** it does not acquire or release a keyed mutex
- **AND** does not call repository get, get-or-create, or save
- **AND** does not reload the state embedded in the projection
- **AND** does not invoke `StrategyRuntimeOrchestrator` or handoff dispatch

#### Scenario: Leave adapters and adjacent branches outside
- **WHEN** the operation runs
- **THEN** it performs no HTTP or ABI DTO/codec adaptation
- **AND** performs no Engine call or open-position lookup
- **AND** does not process the open-trade branch, fill webhook, or
  execution-event lifecycle
