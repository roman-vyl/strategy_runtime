# entry-remainder-cancel Specification

## Purpose
In touch_trigger mode, Runtime asks ABI to cancel the unfilled remainder of a partially filled entry order once the lifetime frozen at the first fill has passed, records the mark on the trade cycle, and never lets a failed cancel or save stop position management.
## Requirements
### Requirement: Runtime asks ABI to cancel the entry remainder once the frozen boundary is reached
On every committed bar processed for an instance whose current trade cycle has an open position and a frozen entry
context, after the first-fill freeze and the existing entry-bar guard and before routing to the open-trade use case,
`StrategyRuntimeOrchestrator` SHALL call ABI's entry-remainder cancel for that cycle exactly when all of these hold:
`frozen_entry_context.entry_order_expires_at_bar` is non-null, `current_trade_cycle.entry_remainder_cancelled` is
`false`, and `bar_open_time_ms + timeframe_ms >= entry_order_expires_at_bar` (the same comparison and shared function
`touch_trigger` entry reconciliation uses). Runtime SHALL send only `strategy_instance_id` and `trade_cycle_id`; it
SHALL NOT store or send any exchange order identifier.

#### Scenario: No call before the boundary
- **WHEN** the base timeframe is `5m`, `entry_order_expires_at_bar` is 12:25, and the processed bar opens at 12:15
- **THEN** Runtime makes no entry-remainder cancel call on that bar

#### Scenario: One call on the boundary bar
- **WHEN** the processed bar opens at 12:20 for the same cycle and the mark is `false`
- **THEN** Runtime makes exactly one entry-remainder cancel call for that cycle on that bar

#### Scenario: A late first fill calls on the same bar
- **WHEN** the first fill is first observed on a bar already at or past the boundary
- **THEN** Runtime freezes the cycle and makes the call on that same bar

#### Scenario: ema_anchor never calls
- **WHEN** `entry_order_expires_at_bar` is `null`
- **THEN** Runtime never makes an entry-remainder cancel call for that cycle

#### Scenario: Recovery markers keep their precedence
- **WHEN** the instance has a pending entry or close recovery marker
- **THEN** the bar returns before the step, exactly as today, and no call is made

### Requirement: A confirmed answer sets the mark once and stops further calls
Either ABI success status, `entry_remainder_cancelled` or `entry_order_already_terminal`, SHALL produce a new state with
`current_trade_cycle.entry_remainder_cancelled = true`, saved before the bar continues. Once the mark is `true`, Runtime
SHALL make no further call for that cycle, including after a restart.

#### Scenario: Cancelled answer sets the mark
- **WHEN** ABI answers `entry_remainder_cancelled`
- **THEN** the saved state has `entry_remainder_cancelled = true` and the bar continues with that state

#### Scenario: Already-terminal answer sets the mark
- **WHEN** ABI answers `entry_order_already_terminal`
- **THEN** the saved state has `entry_remainder_cancelled = true`

#### Scenario: No call after the mark, also after restart
- **WHEN** the mark is `true` and later bars are processed, before or after a Runtime restart
- **THEN** Runtime makes no entry-remainder cancel call for that cycle

### Requirement: A failed call never stops position management
Any failure of the call — timeout or network failure, a documented ABI rejection, an internal ABI failure, or a
malformed response — SHALL leave the state unchanged (mark `false`), SHALL NOT raise out of the bar, and the bar SHALL
continue to the normal open-trade evaluation and position management. The next processed bar retries under the same
rule.

#### Scenario: Timeout, then retry
- **WHEN** the call times out on the boundary bar
- **THEN** position management for that bar runs as usual
- **AND** the next bar makes the call again

#### Scenario: Rejection does not stop the bar
- **WHEN** ABI answers `422 entry_not_filled` or `500 internal_error`
- **THEN** the mark stays `false` and position management for that bar runs as usual

### Requirement: The ABI client sends the exact narrow request
The position-management HTTP client SHALL provide `cancel_entry_remainder(strategy_instance_id, trade_cycle_id)` that
sends `POST /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/entry-remainder/cancel` with body
`{}`, under the same transport, single bounded attempt and timeout as the other position-management calls. A success
SHALL be accepted only as a closed object with the requested `strategy_instance_id` and `trade_cycle_id`, `status` in
`entry_remainder_cancelled | entry_order_already_terminal`, and `executed_quantity` exact-decimal text or `null`; any
other body is a protocol failure. Documented rejections and unavailability use the client's existing error classes.

#### Scenario: Exact request
- **WHEN** Runtime calls `cancel_entry_remainder("s1", "c1")`
- **THEN** ABI receives `POST /v1/strategy-instances/s1/trade-cycles/c1/entry-remainder/cancel` with body `{}`

#### Scenario: Mismatched identity is a protocol failure
- **WHEN** the success body names another `trade_cycle_id`
- **THEN** the client raises its protocol-failure error

### Requirement: Both outcomes are journaled
Runtime SHALL append `entry_remainder_cancelled` with `strategy_instance_id`, `trade_cycle_id`, `bar_open_time_ms`,
`status`, and `executed_quantity` after a confirmed answer, and `entry_remainder_cancel_failed` with
`strategy_instance_id`, `trade_cycle_id`, `bar_open_time_ms`, and the error class after a failure.

#### Scenario: Confirmed cancel is journaled
- **WHEN** ABI confirms `entry_remainder_cancelled` with `executed_quantity` `"0.004"`
- **THEN** the journal has one `entry_remainder_cancelled` event with that status and quantity

#### Scenario: Failure is journaled
- **WHEN** the call times out
- **THEN** the journal has one `entry_remainder_cancel_failed` event naming the timeout class

