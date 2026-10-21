## ADDED Requirements

### Requirement: Applied entry-order values are journaled

The processing journal MUST provide an `entry_package_applied` event, and Runtime MUST
emit one for every `entry_package_applied` response that carries the entry-order values,
with the received values verbatim, before the state is applied, without using them in
any decision or storing them in durable state.

#### Scenario: Applied response with values
- **WHEN** ABI returns `entry_package_applied` with the four values
- **THEN** one event is appended with `strategy_instance_id` in the envelope and `trade_cycle_id` plus the four values exactly as received in the payload

#### Scenario: No values in the response
- **WHEN** the applied response carries none of the four values, or the response is a cancel, absent or error outcome
- **THEN** no `entry_package_applied` event is appended

#### Scenario: Journal failure
- **WHEN** appending the event fails
- **THEN** the failure is absorbed and counted and reconciliation proceeds unchanged

### Requirement: The new event uses the existing journal mechanism

The `entry_package_applied` event MUST be written by the existing processing journal
adapter through the existing event envelope, carry `trade_cycle_id` in its payload, and
MUST NOT change the envelope fields, `schema_version`, or any other event type.

#### Scenario: Event shape
- **WHEN** an `entry_package_applied` event is written
- **THEN** the envelope has the same fields and `schema_version` as `live_entry_evaluated` and the payload holds `trade_cycle_id` and the four values

#### Scenario: Existing event type
- **WHEN** a `live_entry_evaluated` event is written
- **THEN** it is unchanged
