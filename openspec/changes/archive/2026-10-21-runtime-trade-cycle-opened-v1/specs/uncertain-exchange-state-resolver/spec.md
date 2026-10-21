## ADDED Requirements

### Requirement: An uncertain Apply resolved as position_open journals the Open Trade transition after the save
When an uncertain Apply resolves as `position_open` and the reconstructed, frozen state was durably saved, the resolver SHALL write one `trade_cycle_opened` record with `bar_open_time_ms: null` and the recovery response's `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id` and `entry_order_id`. An uncertain removal resolved as `position_open` does not freeze the cycle and SHALL write no record; the bar path writes it when it freezes the cycle.

#### Scenario: Uncertain Apply resolved as position_open
- **WHEN** the resolver reconstructs and freezes the cycle from a `position_open` response and the save succeeds
- **THEN** exactly one `trade_cycle_opened` record is written after the save with `bar_open_time_ms: null`

#### Scenario: Uncertain removal resolved as position_open
- **WHEN** the resolver clears `pending_entry_recovery` for a `position_open` response on an existing cycle
- **THEN** no `trade_cycle_opened` record is written by the resolver
