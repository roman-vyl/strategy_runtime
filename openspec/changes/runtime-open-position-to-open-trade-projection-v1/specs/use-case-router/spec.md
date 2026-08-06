## MODIFIED Requirements

### Requirement: Open-trade routing fails closed before any Engine call
For `resolved.position_open = true`, the router SHALL construct
`OpenTradeProjectionRequest` and call
`StrategyEngineOpenTradePort.project_open_trade(...)` exactly once when the
resolved runtime state's current trade cycle carries a non-null
`frozen_entry_context`, and SHALL raise the existing
`OpenTradeContextUnavailable` without calling either Engine port when it
does not. Freezing that context is not the router's responsibility — it is
`StrategyRuntimeOrchestrator`'s, upstream of routing; the router only reads
what is already there.

#### Scenario: Route an open position with a frozen entry context
- **WHEN** `resolved.position_open` is `true` and
  `resolved.runtime_state.current_trade_cycle.frozen_entry_context` is not
  null
- **THEN** the router builds `OpenTradeProjectionRequest` from the
  registered spec snapshot and the frozen context
- **AND** calls `StrategyEngineOpenTradePort.project_open_trade(...)`
  exactly once
- **AND** returns `OpenTradeProjectedStrategyInstance`
- **AND** does not call live-entry projection

#### Scenario: Fail closed without a frozen entry context
- **WHEN** `resolved.position_open` is `true` and
  `resolved.runtime_state.current_trade_cycle` is null or its
  `frozen_entry_context` is null
- **THEN** the router raises `OpenTradeContextUnavailable(unit
  .strategy_instance_id)`
- **AND** does not construct `OpenTradeProjectionRequest`
- **AND** does not call `StrategyEngineOpenTradePort`

#### Scenario: No fill-fact value is read directly from the resolved fact
- **WHEN** the router builds an open-trade request
- **THEN** `resolved.first_fill_at_ms` and `resolved.average_entry_price`
  are not read, copied, renamed, or otherwise made to reach any Strategy
  Engine request field
- **AND** `entry_bar_open_time_ms` is read only from
  `frozen_entry_context.entry_bar_open_time_ms`, never recomputed by the
  router
- **AND** no legacy field name (`entry_bar_open_time_ms` as a top-level
  resolved fact, `executed_entry_price`) is synthesized anywhere in the
  router

#### Scenario: Live-entry routing is unaffected
- **WHEN** `resolved.position_open` is `false`
- **THEN** the router builds `LiveEntryProjectionRequest` and calls
  `StrategyEngineLiveEntryPort.project_live_entry(...)` exactly as before
  this change

#### Scenario: The fail-closed failure propagates through the existing boundary
- **WHEN** `OpenTradeContextUnavailable` is raised for a missing frozen
  context
- **THEN** it propagates uncaught out of `StrategyRuntimeOrchestrator
  .process(...)` exactly like any other router failure
- **AND** `CommittedBarOrchestrator` converts it into the existing failed
  `StrategyCycleDispatchOutcome`, journaled by `JsonlProcessingJournal` —
  no new error-handling path is introduced

## ADDED Requirements

### Requirement: Open-trade request mapping is exact
The router SHALL build `OpenTradeProjectionRequest` from `runtime_state
.strategy_id`, `registered_spec_snapshot.{raw_spec,instrument,
base_timeframe}`, the current processing unit's committed bar open time,
and `frozen_entry_context.{desired_entry,entry_bar_open_time_ms}` — never
from `unit.deployment` and never from `average_entry_price`.

#### Scenario: Map the open-trade request
- **WHEN** an open position with a frozen entry context is routed
- **THEN** the request's `strategy_id`, `raw_spec`, `ticker`, and
  `base_timeframe` come from `runtime_state.strategy_id` and
  `registered_spec_snapshot`, not from `unit.deployment`
- **AND** `target_bar_open_time_ms` is the current processing unit's
  committed bar open time
- **AND** `desired_entry` is `frozen_entry_context.desired_entry` unchanged
- **AND** `entry_bar_open_time_ms` is
  `frozen_entry_context.entry_bar_open_time_ms` unchanged
- **AND** `average_entry_price` does not appear anywhere in the request

#### Scenario: Wrap the Engine response without interpreting it
- **WHEN** `project_open_trade(...)` returns `OpenTradeProjectionResponse`
- **THEN** the router wraps its `desired_protection`, `close_signal`, and
  `diagnostics` unchanged into `PositionManagementRecipe`
- **AND** returns `OpenTradeProjectedStrategyInstance(source=item,
  position_management_recipe=recipe)`
- **AND** does not replace protection, issue a close command, or mutate
  state
