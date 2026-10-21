## ADDED Requirements

### Requirement: Pending close recovery journals a confirmed closure after the save
When a pending-close attempt receives a confirmation carrying a closure, the resolver SHALL apply and save the state through the existing confirmation path, and only then journal `trade_cycle_closed` with `bar_open_time_ms: null`. A confirmation without a closure SHALL clear state as today and write no record.

#### Scenario: Stop filled while the close was pending
- **WHEN** `pending_close_recovery` is set and ABI answers the close with a `stop_loss` closure
- **THEN** the cycle and the marker are cleared, and one `trade_cycle_closed` record with reason `stop_loss` follows the save
