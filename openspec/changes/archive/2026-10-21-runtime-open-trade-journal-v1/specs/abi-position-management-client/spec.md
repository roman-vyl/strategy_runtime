## ADDED Requirements

### Requirement: Protection success bodies identify the protective orders
The adapter SHALL require exactly six keys in the protection `200` success body: `strategy_instance_id`, `trade_cycle_id`, `status`, `stop_price`, `take_price`, `protection_orders`. `protection_orders` SHALL be an object with exactly `quantity` (positive exact decimal text), `stop` and `take`, each of the two an object with exactly `order_id` (non-empty string) and `trigger_price` (positive exact decimal text). Both legs SHALL be present even when `take_price` is `null`. Any other shape SHALL raise `PositionManagementExecutionProtocolError`. `ProtectionAppliedConfirmation` SHALL carry both legs unchanged; they SHALL NOT be compared with the command, persisted in Runtime state, or used in any decision. The existing echo check of `stop_price` and `take_price` against the command SHALL stay.

#### Scenario: Both protective orders reported
- **WHEN** a success body carries `protection_orders` with valid `stop` and `take`
- **THEN** the confirmation carries `quantity` and both legs' `order_id` and `trigger_price` unchanged

#### Scenario: No take requested
- **WHEN** the command has `take_price: null` and the body carries `take_price: null` and a valid `take` leg
- **THEN** the confirmation is accepted with the `take` leg

#### Scenario: Old body
- **WHEN** a success body lacks `protection_orders`
- **THEN** the adapter raises `PositionManagementExecutionProtocolError`

#### Scenario: Malformed leg
- **WHEN** a leg lacks a key, has an extra key, an empty `order_id`, a non-positive or non-decimal `trigger_price`, or `quantity` missing or invalid
- **THEN** the adapter raises `PositionManagementExecutionProtocolError`
