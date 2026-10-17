## ADDED Requirements

### Requirement: Applied entry-order values are journaled

The processing journal MUST provide an `entry_package_applied` event, and Runtime MUST
emit one for every `entry_package_applied` response that carries the entry-order values,
with the received values verbatim, before the state is applied, without using them in
any decision or storing them in durable state.

#### Scenario: Applied response with values
- **WHEN** ABI returns `entry_package_applied` with the four values
- **THEN** one event is appended with `strategy_instance_id`, `trade_cycle_id` and the four values exactly as received

#### Scenario: No values in the response
- **WHEN** the applied response carries none of the four values, or the response is a cancel, absent or error outcome
- **THEN** no `entry_package_applied` event is appended

#### Scenario: Journal failure
- **WHEN** appending the event fails
- **THEN** the failure is absorbed and counted and reconciliation proceeds unchanged

### Requirement: Envelope may carry a trade cycle id

The journal envelope MUST accept an optional top-level `trade_cycle_id`, serialized only
when set, and MUST NOT change `schema_version` or the shape of events that do not set it.

#### Scenario: Event with a cycle
- **WHEN** an `entry_package_applied` event is written
- **THEN** its envelope has `trade_cycle_id`

#### Scenario: Existing event type
- **WHEN** a `live_entry_evaluated` event is written
- **THEN** its payload and envelope are unchanged and it has no `trade_cycle_id`
