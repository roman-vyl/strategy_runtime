## ADDED Requirements

### Requirement: Open-trade evaluation event
The processing journal SHALL provide an `open_trade_evaluated` event (schema version 2, `strategy_instance_id` in the envelope) with payload `instrument`, `timeframe`, `bar_open_time_ms`, `trade_cycle_id`, `side`, `desired_protection` (`stop_price`, `take_price`) and `close_signal` (`active`, `reason`, `component_id`, `layer`). Decimals SHALL be exact decimal text; an absent `take_price` and absent close signal fields SHALL be JSON `null`. The payload SHALL NOT contain Engine diagnostics. A write failure SHALL NOT raise into orchestration and SHALL NOT change Runtime state.

#### Scenario: Short position with no take
- **WHEN** the event is written for a short position whose desired protection has no take price
- **THEN** the payload has `side: "short"` and `desired_protection.take_price: null`

#### Scenario: Journal write fails
- **WHEN** appending `open_trade_evaluated` fails
- **THEN** orchestration continues and the state is unchanged

### Requirement: Protection applied event
The processing journal SHALL provide a `protection_applied` event (schema version 2, `strategy_instance_id` in the envelope) with payload `trade_cycle_id`, `bar_open_time_ms`, `requested_protection` and `confirmed_protection` (each `{stop_price, take_price}`), `position_quantity`, `stop_order` and `take_order` (each `{order_id, trigger_price}`). Requested levels SHALL be the ones Runtime sent; confirmed levels, quantity and orders SHALL be exactly as ABI returned them. `take_price` SHALL be JSON `null` when absent while `take_order` is still present; nothing SHALL be hidden or substituted. A write failure SHALL NOT raise into orchestration and SHALL NOT change Runtime state.

#### Scenario: No take requested
- **WHEN** Runtime requested `take_price: null`
- **THEN** the record has `take_price: null` in both `requested_protection` and `confirmed_protection`, and `take_order` with the id and trigger price of the take order ABI actually keeps on the exchange

#### Scenario: Journal write fails
- **WHEN** appending `protection_applied` fails
- **THEN** position management continues and the confirmed protection is still applied to state
