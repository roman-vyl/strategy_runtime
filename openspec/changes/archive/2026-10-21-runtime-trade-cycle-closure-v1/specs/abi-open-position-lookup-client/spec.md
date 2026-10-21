## ADDED Requirements

### Requirement: The open-position success body accepts an optional closure
The adapter SHALL accept `closure` as a fourth, optional key of the `200` success body. A missing key or `null` SHALL decode as no closure. A present object SHALL be closed with exactly `strategy_instance_id`, `trade_cycle_id`, `reason`, `order_id`, `order_link_id`, `parent_order_link_id`; `reason` SHALL be `stop_loss`, `take_profit` or `runtime_signal`; `order_id` SHALL be a non-empty string; `order_link_id` SHALL be a non-empty string for `runtime_signal` and `null` otherwise; `parent_order_link_id` SHALL be a non-empty string for `stop_loss` and `take_profit` and `null` otherwise. A closure with `position_open: true`, or any other shape, SHALL raise `OpenPositionLookupProtocolError`. Any key other than the four SHALL still be rejected.

#### Scenario: Body without the key
- **WHEN** a `200` body has only the three existing keys
- **THEN** it decodes as before with no closure

#### Scenario: Stop-loss closure
- **WHEN** a `200` body has `position_open: false` and a valid `stop_loss` closure
- **THEN** the response carries the closure unchanged

#### Scenario: Closure on an open position
- **WHEN** `position_open` is `true` and `closure` is an object
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
