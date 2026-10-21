## ADDED Requirements

### Requirement: The close success body accepts an optional closure
The close adapter SHALL accept `closure` as an optional fourth key of the `trade_cycle_closed` body, with the closure shape of the open-position client. A present closure SHALL have `strategy_instance_id` and `trade_cycle_id` equal to the sent command, otherwise the adapter raises a protocol failure. `PositionClosedConfirmation` SHALL carry the closure or `None`.

#### Scenario: Stop beat the close command
- **WHEN** ABI answers a close with `trade_cycle_closed` and a `stop_loss` closure
- **THEN** the adapter returns a confirmation carrying that closure

#### Scenario: Body without the key
- **WHEN** the body has only the three existing keys
- **THEN** the confirmation carries no closure
