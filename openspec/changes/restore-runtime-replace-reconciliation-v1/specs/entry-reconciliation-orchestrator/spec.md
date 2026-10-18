## MODIFIED Requirements

### Requirement: Cancel reuses decision-owned identity
The orchestrator SHALL construct `Cancel` commands without reserving a new
trade-cycle identity, both for a `Cancel` decision and for the cancel step of
a `Replace` decision.

#### Scenario: Build Cancel from its decision
- **WHEN** pure reconciliation returns `Cancel`
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory`
- **AND** invokes the existing command builder without an apply-only identity
- **AND** the builder uses the `trade_cycle_id` carried by the decision

#### Scenario: Build the cancel step of Replace
- **WHEN** pure reconciliation returns `Replace(C, Y)`
- **THEN** the cancel step uses the existing command builder with
  `Cancel(C)` and no apply-only identity
- **AND** no identity is reserved before that cancel step is confirmed absent

## ADDED Requirements

### Requirement: Replace executes as confirmed CANCEL then fresh APPLY
The orchestrator SHALL execute `Replace(C, Y)` within one invocation as two
sequential, independently confirmed operations built from the existing
`Cancel(C)` and `Apply(Y)` decisions, with no new command, confirmation, or
ABI capability.

#### Scenario: Successful replace in one bar
- **WHEN** pure reconciliation returns `Replace(C, Y)`
- **AND** the cancel command for C returns a matching
  `EntryAbsentConfirmation`
- **AND** the apply command for Y with a newly reserved identity N returns a
  matching `EntryAppliedConfirmation`
- **THEN** the execution port was invoked exactly twice, first with the
  cancel command (`desired_entry: null`, `trade_cycle_id = C`), then with
  the apply command (`desired_entry = Y`, `trade_cycle_id = N`)
- **AND** `TradeCycleIdFactory` was invoked exactly once, after the cancel
  confirmation
- **AND** the returned aggregate has `current_trade_cycle` with identity N
  and applied desired entry Y, and `pending_entry_recovery = null`
- **AND** `entry_package_applied` is journaled for N exactly as for `Apply`

#### Scenario: Apply is never sent before confirmed absence
- **WHEN** the cancel step raises any exception or returns a value outside
  `EntryAbsentConfirmation`
- **THEN** no identity is reserved and no apply command is sent
- **AND** the failure propagates exactly as for a plain `Cancel`
- **AND** the durable state remains cycle C with `pending_entry_recovery =
  {C}`, for the existing uncertain-removal path

#### Scenario: Contradictory cancel confirmation fails closed
- **WHEN** the cancel confirmation does not match C
- **THEN** `EntryReconciliationInvariantError` propagates
- **AND** no apply command is sent

#### Scenario: Apply failure after the boundary
- **WHEN** the apply step raises any exception
- **THEN** the orchestrator does not retry and does not re-send the cancel
- **AND** the durable state is the boundary state (no current cycle,
  `pending_entry_recovery = {N}`), for the existing uncertain-apply path

### Requirement: Replace has one durable boundary between its operations
After the cancel step of `Replace` is confirmed absent and before the apply
request reaches ABI, the orchestrator SHALL perform exactly one durable save
whose aggregate has `current_trade_cycle = null` and
`pending_entry_recovery = {N}`, where N is the identity the apply command
carries.

#### Scenario: Marker sequence of a replace
- **WHEN** `Replace(C, Y)` runs to success
- **THEN** durable saves inside the orchestrator are, in order: the existing
  pre-cancel save with `pending_entry_recovery = {C}` on cycle C, then the
  boundary save with no cycle and `pending_entry_recovery = {N}`
- **AND** the final applied aggregate is saved by the outer orchestrator as
  for any confirmed transition

#### Scenario: Crash between confirmed absence and the boundary save
- **WHEN** the process stops after the cancel confirmation but before the
  boundary save completes
- **THEN** durable state is cycle C with `pending_entry_recovery = {C}`
- **AND** recovery resolves it as an uncertain removal, and a later bar
  decides afresh

#### Scenario: Crash after the boundary save
- **WHEN** the process stops after the boundary save
- **THEN** durable state has no current cycle and
  `pending_entry_recovery = {N}`
- **AND** recovery resolves it as an uncertain apply of N, whether or not the
  apply request reached ABI
