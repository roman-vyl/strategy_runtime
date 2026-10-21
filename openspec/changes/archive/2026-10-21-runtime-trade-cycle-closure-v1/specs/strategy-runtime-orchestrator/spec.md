## ADDED Requirements

### Requirement: A proven closure ends the cycle before routing
When the resolved state carries a closure, Runtime SHALL, inside the same keyed critical section and before first-fill freezing and routing: verify that the closure's `strategy_instance_id` and `trade_cycle_id` equal the state and its current trade cycle; durably save the state with `current_trade_cycle = None` and `pending_close_recovery = None`; then journal `trade_cycle_closed` with the committed bar's `bar_open_time_ms`; and return. Runtime SHALL NOT invoke Engine, entry reconciliation, position management or any ABI write for that bar. An identity mismatch SHALL raise and leave state unchanged. The transition SHALL take no close decision or command.

#### Scenario: Stop filled since the previous bar
- **WHEN** the lookup returns a `stop_loss` closure for the current cycle
- **THEN** the saved state has no current trade cycle, one `trade_cycle_closed` record follows the save, and no Engine call or entry is made on this bar

#### Scenario: Next bar after the closure
- **WHEN** the following bar is processed
- **THEN** Runtime makes no lookup and evaluates live entry as for any instance without a cycle

#### Scenario: Mismatched closure
- **WHEN** the closure's `trade_cycle_id` differs from the current cycle
- **THEN** Runtime raises, saves nothing and journals nothing

#### Scenario: Flat answer without closure is not a close
- **WHEN** the lookup returns `position_open: false` without a closure for a cycle with a frozen entry context
- **THEN** Runtime does not end the cycle
