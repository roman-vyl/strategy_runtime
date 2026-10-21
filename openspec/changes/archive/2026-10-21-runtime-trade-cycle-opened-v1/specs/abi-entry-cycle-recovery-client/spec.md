## ADDED Requirements

### Requirement: Recovery-state success bodies identify the proved entry order
The adapter SHALL require exactly six keys in every `200` recovery-state success body: `recovery_state`, `applied_entry_package`, `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id`, `entry_order_id`. For `position_open`, `entry_order_link_id` SHALL be a non-empty string and `entry_order_id` SHALL be a non-empty string or `null`, and `PositionOpenRecoveryState` SHALL carry both. For every other `recovery_state`, both SHALL be `null`. Any other key set or value SHALL raise `AbiEntryCycleRecoveryProtocolError`.

#### Scenario: position_open with both identifiers
- **WHEN** a `position_open` body carries a non-empty `entry_order_link_id` and a non-empty `entry_order_id`
- **THEN** `PositionOpenRecoveryState` carries both values unchanged

#### Scenario: position_open without an exchange order id
- **WHEN** a `position_open` body carries `entry_order_id: null`
- **THEN** `PositionOpenRecoveryState.entry_order_id` is `null`

#### Scenario: Other states
- **WHEN** an `entry_order_live`, `entry_order_not_found`, `terminal_without_fill` or `terminal_after_fill` body carries a non-null identifier, or lacks either key
- **THEN** the adapter raises `AbiEntryCycleRecoveryProtocolError`
