## ADDED Requirements

### Requirement: Declined acknowledgement maps to a declined outcome
When `AbiEntryPackagePort.send` returns `EntryPackageDeclined`, the bridge SHALL
return one transport-free `EntryDeclinedOutcome` with the same
`strategy_instance_id`, `trade_cycle_id`, `decline_reason`, and
`decline_message`. The bridge SHALL NOT raise, retry, mutate state, or convert
the answer into an applied or absent confirmation.

#### Scenario: Map a declined answer
- **WHEN** the port returns `EntryPackageDeclined`
- **THEN** the bridge returns `EntryDeclinedOutcome` with the four values unchanged
- **AND** calls the port exactly once

#### Scenario: Errors keep their mapping
- **WHEN** the port returns a public error or raises a timeout, network, or protocol failure
- **THEN** the bridge raises `EntryReconciliationExecutionError` as before
