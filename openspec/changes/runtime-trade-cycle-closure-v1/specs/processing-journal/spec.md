## ADDED Requirements

### Requirement: Every confirmed trade-cycle closure is journaled after the durable save
Runtime SHALL write `trade_cycle_closed` (schema version 2, `strategy_instance_id` in the envelope) with payload `trade_cycle_id`, `bar_open_time_ms`, `reason`, `order_id`, `order_link_id`, `parent_order_link_id`, taken verbatim from ABI's closure, only after the state without the cycle was durably saved. `bar_open_time_ms` SHALL be the committed bar on which Runtime learned of the closure, or `null` when it was learned by the pending-close resolver. The record SHALL NOT be used in any decision.

#### Scenario: Closure learned on a bar
- **WHEN** a bar ends a cycle by a closure or by a confirmed close carrying one
- **THEN** one record is written after the save with that bar's `bar_open_time_ms`

#### Scenario: Save failed
- **WHEN** saving the state without the cycle fails
- **THEN** no `trade_cycle_closed` record is written
