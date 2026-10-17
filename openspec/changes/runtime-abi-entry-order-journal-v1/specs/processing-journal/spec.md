## ADDED Requirements

### Requirement: Received cycle execution state is journaled

The processing journal MUST provide a `cycle_execution_state_observed` event, and
Runtime MUST emit one for every received ABI entry-package applied response,
recovery-state `entry_order_live`/`position_open` response and open-position
`position_open: true` response that carries physical data, with the received values
verbatim and without using them in any decision or persisting them in durable state.

#### Scenario: Applied response with a pending order
- **WHEN** ABI confirms an applied entry with `cycle_execution_state.entry_order`
- **THEN** one event is appended with `strategy_instance_id`, `trade_cycle_id`, `source_operation` `entry_package_applied`, the applied desired entry and the received values

#### Scenario: Open position
- **WHEN** an open-position lookup returns `position_open: true` with `executed_quantity`
- **THEN** one event is appended with `source_operation` `open_position`, `applied_desired_entry` null and the received execution values

#### Scenario: No physical data
- **WHEN** the response lacks `cycle_execution_state` or `executed_quantity`, or is an absent, terminal, not-found or error response
- **THEN** no `cycle_execution_state_observed` event is appended

#### Scenario: Journal failure
- **WHEN** appending the event fails
- **THEN** the failure is absorbed and counted and reconciliation, recovery and state saving proceed unchanged

### Requirement: Envelope may carry a trade cycle id

The journal envelope MUST accept an optional top-level `trade_cycle_id`, serialized only
when set, and `schema_version` MUST be 3 for events written after this change.

#### Scenario: Event with a cycle
- **WHEN** a `cycle_execution_state_observed` event is written
- **THEN** its envelope has `trade_cycle_id` and `schema_version` 3

#### Scenario: Existing event type
- **WHEN** a `live_entry_evaluated` event is written
- **THEN** its payload is unchanged and it has no `trade_cycle_id`
