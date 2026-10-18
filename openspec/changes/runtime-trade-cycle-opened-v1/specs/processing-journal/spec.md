## ADDED Requirements

### Requirement: Every Open Trade transition is journaled after the durable save
Runtime SHALL write `trade_cycle_opened` (schema version 2, `strategy_instance_id` in the envelope) with payload `trade_cycle_id`, `bar_open_time_ms`, `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id`, `entry_order_id`, only after the state with the newly frozen entry context was durably saved. The record SHALL mean the first confirmed execution of the cycle's entry order, a partial one included; `average_entry_price` SHALL be ABI's value at that observation, not a final entry price. `bar_open_time_ms` SHALL be the committed bar on which Runtime made the transition, or `null` on the recovery path. A write failure SHALL NOT raise into orchestration and SHALL NOT change Runtime state. The record SHALL NOT be used in any decision.

#### Scenario: Partial fill
- **WHEN** the transition is made from a partially filled entry order
- **THEN** the record is written with ABI's current `average_entry_price`

#### Scenario: Missing exchange order id
- **WHEN** ABI reported `entry_order_id: null`
- **THEN** the record carries `entry_order_id: null`

#### Scenario: Journal write fails
- **WHEN** appending the record fails
- **THEN** the failure counter grows, no exception reaches orchestration, and the saved state is unchanged
