## ADDED Requirements

### Requirement: The bar-path Open Trade transition is journaled once after the save
When the first-fill transition on the bar path produces a new state and that state was durably saved, Runtime SHALL write one `trade_cycle_opened` record with the committed bar's `bar_open_time_ms`, the frozen `first_fill_at_ms`, and the resolved lookup's `average_entry_price`, `entry_order_link_id` and `entry_order_id`. When the cycle was already frozen, Runtime SHALL write no record. The record SHALL NOT change the flow of the bar.

#### Scenario: First freeze on a bar
- **WHEN** a bar resolves `position_open: true` for a cycle without a frozen entry context and the save succeeds
- **THEN** exactly one `trade_cycle_opened` record is written after the save, with that bar's `bar_open_time_ms`

#### Scenario: Later bars with the same open position
- **WHEN** a later bar resolves `position_open: true` for the same, already frozen cycle
- **THEN** no `trade_cycle_opened` record is written

#### Scenario: Save failed
- **WHEN** saving the frozen state fails
- **THEN** no `trade_cycle_opened` record is written
