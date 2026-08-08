## REMOVED Requirements

### Requirement: Open-trade mapping requires frozen entry context
**Reason**: This requirement assumed the router could honestly construct
`OpenTradeProjectionRequest` once local context (a frozen current trade
cycle plus the ABI-reported entry facts) looked complete. The ABI
open-position alignment renames those facts to `first_fill_at_ms` /
`average_entry_price` and this change makes no design decision about
whether or how an exchange fill timestamp may stand in for Engine's
existing `entry_bar_open_time_ms` request field. Constructing the request
under the old mapping would make that undesigned decision implicitly.
**Migration**: See the new "Open-trade routing fails closed before any
Engine call" requirement below. `OpenTradeContextUnavailable` is still
raised for `position_open=true`; the router no longer distinguishes
"context incomplete" from "context complete" before raising it, and no
longer constructs `OpenTradeProjectionRequest` or calls
`StrategyEngineOpenTradePort` in either case.

## ADDED Requirements

### Requirement: Open-trade routing fails closed before any Engine call
The router SHALL NOT construct `OpenTradeProjectionRequest` and SHALL NOT
call `StrategyEngineOpenTradePort.project_open_trade` when
`resolved.position_open` is `true`. It SHALL raise the existing
`OpenTradeContextUnavailable` unconditionally for this case, as a temporary
fail-closed boundary pending a separate future decision on whether or how
ABI-reported fill facts should reach Strategy Engine.

#### Scenario: Fail closed immediately for an open position
- **WHEN** `resolved.position_open` is `true`
- **THEN** the router raises `OpenTradeContextUnavailable(unit
  .strategy_instance_id)` before evaluating the current trade cycle, its
  frozen desired entry, or either fill fact
- **AND** does not construct `OpenTradeProjectionRequest`
- **AND** does not call `StrategyEngineOpenTradePort`

#### Scenario: No fill-fact value is read for Engine mapping
- **WHEN** the router raises for `position_open=true`
- **THEN** `resolved.first_fill_at_ms` and `resolved.average_entry_price`
  are not read, copied, renamed, or otherwise made to reach any Strategy
  Engine request field
- **AND** no legacy field name (`entry_bar_open_time_ms`,
  `executed_entry_price`) is synthesized anywhere in the router

#### Scenario: Live-entry routing is unaffected
- **WHEN** `resolved.position_open` is `false`
- **THEN** the router builds `LiveEntryProjectionRequest` and calls
  `StrategyEngineLiveEntryPort.project_live_entry(...)` exactly as before
  this change

#### Scenario: The fail-closed failure propagates through the existing boundary
- **WHEN** `OpenTradeContextUnavailable` is raised
- **THEN** it propagates uncaught out of `StrategyRuntimeOrchestrator
  .process(...)` exactly like any other router failure
- **AND** `CommittedBarOrchestrator` converts it into the existing failed
  `StrategyCycleDispatchOutcome`, journaled by `JsonlProcessingJournal` —
  no new error-handling path is introduced
