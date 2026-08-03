## MODIFIED Requirements

### Requirement: Open-trade mapping requires frozen entry context
The router SHALL call open-trade projection only when the runtime state and
resolved facts contain complete immutable entry context, and it SHALL NOT
send Runtime-owned instance identity or the resolver's `average_entry_price`
fact to Engine. Strategy Engine SHALL calculate position management from the
frozen `planned_entry_price`; the ABI-reported average entry price remains a
Runtime/ABI execution fact.

#### Scenario: Reject missing context before Engine
- **WHEN** the current trade cycle is absent, its singular desired entry is
  not frozen, or either fill fact (`first_fill_at_ms` or
  `average_entry_price`) is absent
- **THEN** the router raises `OpenTradeContextUnavailable`
- **AND** does not call either Engine port

#### Scenario: Map the open-trade request
- **WHEN** an open position has complete context
- **THEN** the request contains strategy ID, raw spec, market, base
  timeframe, and target bar
- **AND** contains the frozen `DesiredEntry`
- **AND** contains the resolver-supplied `first_fill_at_ms` value, passed
  through unchanged as Engine's existing `entry_bar_open_time_ms` request
  field — a same-value field-name propagation, not a new timestamp
  computation or candle-grid alignment
- **AND** uses the frozen `DesiredEntry.planned_entry_price` as Engine
  calculation input
- **AND** does not contain `average_entry_price`
- **AND** contains no Runtime strategy-instance ID, Runtime cycle ID, or
  exchange identifier
