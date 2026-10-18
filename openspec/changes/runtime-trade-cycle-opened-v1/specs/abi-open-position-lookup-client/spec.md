## ADDED Requirements

### Requirement: The open-position success body identifies the proved entry order
The adapter SHALL require exactly six keys in the `200` success body: `position_open`, `first_fill_at_ms`, `average_entry_price`, `closure`, `entry_order_link_id`, `entry_order_id`. When `position_open` is `true`, `entry_order_link_id` SHALL be a non-empty string and `entry_order_id` SHALL be a non-empty string or `null`. When `position_open` is `false`, both SHALL be `null`. Any other key set or value SHALL raise `OpenPositionLookupProtocolError`. A `null` `entry_order_id` SHALL be kept as `null`, never replaced by another identifier.

#### Scenario: Open position with both identifiers
- **WHEN** a `200` body has `position_open: true`, a non-empty `entry_order_link_id` and a non-empty `entry_order_id`
- **THEN** the response carries both values unchanged

#### Scenario: Open position without an exchange order id
- **WHEN** a `200` body has `position_open: true`, a non-empty `entry_order_link_id` and `entry_order_id: null`
- **THEN** the response carries `entry_order_id` as `null`

#### Scenario: Body without the new keys
- **WHEN** a `200` body lacks `entry_order_link_id` or `entry_order_id`
- **THEN** the adapter raises `OpenPositionLookupProtocolError`

#### Scenario: Identifiers on a closed position
- **WHEN** a `200` body has `position_open: false` and a non-null `entry_order_link_id` or `entry_order_id`
- **THEN** the adapter raises `OpenPositionLookupProtocolError`

#### Scenario: Open position without a link id
- **WHEN** a `200` body has `position_open: true` and `entry_order_link_id` is `null` or empty
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
