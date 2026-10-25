## MODIFIED Requirements

### Requirement: Execution port is narrow and transport-free
Runtime SHALL define an injected `EntryReconciliationExecutionPort` owned by
the application capability with exactly one operation that accepts an existing
`EntryReconciliationCommand` plus the exact source
`StrategyInstanceRuntimeState` and returns an existing
`SuccessfulEntryConfirmation` or an `EntryDeclinedOutcome`:

```text
execute(
    command: EntryReconciliationCommand,
    source_state: StrategyInstanceRuntimeState,
) -> SuccessfulEntryConfirmation | EntryDeclinedOutcome
```

#### Scenario: Pass command and source-state values
- **WHEN** the orchestrator invokes the execution port
- **THEN** the first argument is the existing transport-free
  `EntryReconciliationCommand`
- **AND** the second argument is the exact `source_state` extracted from the
  projection
- **AND** a normal return is exactly
  `EntryAppliedConfirmation | EntryAbsentConfirmation | EntryDeclinedOutcome`

#### Scenario: Represent execution failure by exception
- **WHEN** external execution cannot produce a successful confirmation or a
  declined outcome
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
`SuccessfulEntryConfirmation` union. An `EntryDeclinedOutcome` SHALL NOT reach
the applier.

#### Scenario: Apply a successful confirmation
- **WHEN** one command has been executed
- **AND** the execution port returns
  `EntryAppliedConfirmation | EntryAbsentConfirmation`
- **THEN** the orchestrator invokes the existing applier exactly once with the
  exact extracted `source_state`, original decision, exact sent command, and
  returned confirmation

#### Scenario: Declined outcome bypasses the applier
- **WHEN** the execution port returns `EntryDeclinedOutcome`
- **THEN** the successful-confirmation applier is not invoked
- **AND** the orchestrator follows "A declined Apply ends the attempt without a
  trade cycle or recovery marker"

#### Scenario: Reject a non-success port result before application
- **WHEN** an execution-port implementation violates its contract by returning
  a value outside `SuccessfulEntryConfirmation` and outside
  `EntryDeclinedOutcome`
- **THEN** the orchestrator raises `EntryReconciliationInvariantError`
- **AND** does not invoke the successful-confirmation applier
- **AND** does not construct replacement state

#### Scenario: Bypass application on execution exception
- **WHEN** the execution port raises an exception
- **THEN** the successful-confirmation applier is not invoked
- **AND** no replacement aggregate is returned

## ADDED Requirements

### Requirement: A declined Apply ends the attempt without a trade cycle or recovery marker
When the execution port returns `EntryDeclinedOutcome` for an `Apply` step
(alone or as the second step of `Replace`), the orchestrator SHALL end the
attempt: durably save the state with `pending_entry_recovery = null`, create no
trade cycle, start no recovery, journal the refusal, and return the saved state.

#### Scenario: No retry and no decision change
- **WHEN** an `Apply` is declined
- **THEN** the orchestrator sends no further request in this invocation
- **AND** changes no trading decision

#### Scenario: Declined Apply with no current cycle
- **WHEN** an `Apply` with a fresh `trade_cycle_id` receives `EntryDeclinedOutcome` with matching identifiers
- **THEN** the durably saved state has `current_trade_cycle = null` and `pending_entry_recovery = null`
- **AND** the save happens in this invocation, after the marker save, even though the returned state equals the bar's source state
- **AND** one `entry_package_declined` journal event is written after the save

#### Scenario: Declined Apply after a confirmed Cancel in Replace
- **WHEN** the `Cancel` step of a `Replace` is confirmed absent and the following `Apply` step receives `EntryDeclinedOutcome`
- **THEN** the returned state has `current_trade_cycle = null` and `pending_entry_recovery = null`
- **AND** it is durably saved

#### Scenario: Next bar runs normally
- **WHEN** the next committed bar for the same instance still produces a desired entry
- **THEN** the ordinary path sends a new `Apply` with a newly reserved `trade_cycle_id`
- **AND** no bar is skipped because of the earlier refusal

#### Scenario: Declined outcome at a Cancel step
- **WHEN** the execution port returns `EntryDeclinedOutcome` for a `Cancel` command
- **THEN** the orchestrator raises `EntryReconciliationInvariantError`
- **AND** performs no further save, so the marker stays as saved

#### Scenario: Declined outcome with mismatched identity
- **WHEN** the declined outcome's `strategy_instance_id` or `trade_cycle_id` differs from the sent command
- **THEN** the orchestrator raises `EntryReconciliationInvariantError` and performs no further save

#### Scenario: Journal failure does not change the result
- **WHEN** writing the `entry_package_declined` event fails
- **THEN** the failure is absorbed and the saved state is returned unchanged
