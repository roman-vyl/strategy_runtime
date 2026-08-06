## REMOVED Requirements

### Requirement: Open-trade routing fails closed before any Engine call
**Reason**: An open position with a frozen entry context now reaches
Strategy Engine instead of failing closed unconditionally.
**Migration**: See "Runtime routes an open position from frozen entry
context".

## ADDED Requirements

### Requirement: Runtime routes an open position from frozen entry context
For `resolved.position_open = true`, the router SHALL route from the
current trade cycle's frozen entry context: build the open-trade request
from the registered spec snapshot, the current committed bar, and that
context (never from `unit.deployment`, never including
`average_entry_price`), call `StrategyEngineOpenTradePort
.project_open_trade(...)` exactly once, and return
`OpenTradeProjectedStrategyInstance` wrapping the response unchanged. When
no frozen entry context is present, it SHALL raise the existing
`OpenTradeContextUnavailable` without calling either Engine port. Routing a
closed position is unaffected.

#### Scenario: Route an open position with a frozen entry context
- **WHEN** `resolved.position_open` is `true` and the current trade cycle's
  `frozen_entry_context` is not null
- **THEN** the request's `strategy_id` comes from
  `resolved.runtime_state.strategy_id`, its `raw_spec`/`ticker`/
  `base_timeframe` come from the registered spec snapshot,
  `target_bar_open_time_ms` from the current committed bar, and
  `desired_entry`/`entry_bar_open_time_ms` from the frozen context,
  unchanged
- **AND** the router calls `project_open_trade(...)` exactly once and does
  not call live-entry projection
- **AND** it returns `OpenTradeProjectedStrategyInstance` wrapping the
  response's `desired_protection`, `close_signal`, and `diagnostics`
  without interpreting them

#### Scenario: Fail closed without a frozen entry context
- **WHEN** `resolved.position_open` is `true` and the current trade cycle
  is null or its `frozen_entry_context` is null
- **THEN** the router raises `OpenTradeContextUnavailable(unit
  .strategy_instance_id)`
- **AND** calls neither Engine port

#### Scenario: Closed-position routing is unchanged
- **WHEN** `resolved.position_open` is `false`
- **THEN** the router builds `LiveEntryProjectionRequest` and calls
  `StrategyEngineLiveEntryPort.project_live_entry(...)` exactly as before
  this change
