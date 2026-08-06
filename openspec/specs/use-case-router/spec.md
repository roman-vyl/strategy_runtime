# use-case-router Specification

## Purpose

Define the scalar Runtime routing boundary that validates one resolved strategy
instance, selects the applicable Strategy Engine projection, and returns a typed
projection without applying it to state.

## Requirements

### Requirement: Runtime routes one resolved processing item
Strategy Runtime SHALL provide a scalar `StrategyUseCaseRouter` that accepts one
`PositionResolvedStrategyInstance` and returns one typed Engine projection.

#### Scenario: Invoke the scalar third step
- **WHEN** state get-or-create and position resolution complete for one processing unit
- **THEN** the orchestrator invokes the router once with that unit and resolved state
- **AND** receives one projection into the same `process(...)` call

#### Scenario: Keep state application and execution outside the router
- **WHEN** the router returns a projection
- **THEN** it has not persisted or mutated repository state
- **AND** has not called ABI or translated Engine output into exchange actions

### Requirement: Router validates strategy-instance correspondence
Before calling Engine, the router SHALL require equal
`strategy_instance_id` values on the processing unit, deployment, and resolved
runtime state.

#### Scenario: Processing unit and deployment differ
- **WHEN** their strategy-instance IDs do not match
- **THEN** the router raises `StrategyInstanceBindingError`
- **AND** does not call either Engine port

#### Scenario: Processing unit and runtime state differ
- **WHEN** their strategy-instance IDs do not match
- **THEN** the router raises `StrategyInstanceBindingError`
- **AND** does not call either Engine port

#### Scenario: Do not repeat identity derivation
- **WHEN** all three derived IDs match
- **THEN** the router does not field-compare raw spec, ticker, or base timeframe

### Requirement: Routing uses only the resolved open-position fact
The router SHALL select the Engine use case from `position_open`.

#### Scenario: Route a closed position
- **WHEN** `position_open` is `false`
- **THEN** the router calls live-entry projection exactly once
- **AND** does not call open-trade projection

#### Scenario: Route an open position
- **WHEN** `position_open` is `true` and required context is present
- **THEN** the router calls open-trade projection exactly once
- **AND** does not call live-entry projection

### Requirement: Live-entry mapping and result are exact
The router SHALL build the live-entry request from the current processing unit
without transmitting Runtime-owned instance identity and SHALL preserve
Engine's singular `desired_entry: DesiredEntry | null` without side selection
or arbitration. Every non-null `DesiredEntry` SHALL contain a `side` of `long`
or `short` and a non-empty, finite, positive exact-decimal
`initial_take_price`; a missing or null take SHALL be rejected before the object
can enter projected Runtime state or future ABI reconciliation.

#### Scenario: Map the live-entry request
- **WHEN** a closed position is routed
- **THEN** the request contains deployment strategy ID, raw spec, ticker, and base timeframe
- **AND** contains the committed bar open time as `target_bar_open_time_ms`
- **AND** does not contain Runtime `strategy_instance_id` or Engine `instance_id`

#### Scenario: Preserve the desired entry
- **WHEN** Engine returns a valid singular `desired_entry`
- **THEN** the projection contains that same `DesiredEntry`
- **AND** its embedded `side` is preserved without Runtime arbitration
- **AND** the entry contains canonical positive initial take text
- **AND** the source processing item is retained

#### Scenario: Preserve no desired entry
- **WHEN** Engine returns `desired_entry = null`
- **THEN** the projection contains `desired_entry = null`
- **AND** Runtime does not fabricate either side

#### Scenario: Reject a null initial take
- **WHEN** an Engine payload contains a `DesiredEntry` whose `initial_take_price` is null
- **THEN** Runtime rejects the desired entry as malformed
- **AND** no desired entry can be sent to ABI reconciliation

#### Scenario: Reject a missing initial take
- **WHEN** an Engine payload contains a `DesiredEntry` without `initial_take_price`
- **THEN** Runtime rejects the desired entry as malformed
- **AND** no desired entry can be sent to ABI reconciliation

#### Scenario: Reject an invalid initial take decimal
- **WHEN** an Engine payload contains a `DesiredEntry` with an empty, non-finite, zero, or negative `initial_take_price`
- **THEN** Runtime rejects the desired entry as malformed
- **AND** no desired entry can be sent to ABI reconciliation

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

### Requirement: Position-management diagnostics are opaque and immutable
The router SHALL preserve open-trade calculation objects without interpretation,
and diagnostics SHALL remain an opaque recursively immutable JSON mapping.

#### Scenario: Preserve arbitrary diagnostics
- **WHEN** Engine returns any JSON-compatible nested diagnostic mapping
- **THEN** all keys and values are preserved
- **AND** nested objects and arrays are recursively immutable
- **AND** Runtime requires no fixed diagnostic field list

#### Scenario: Do not interpret management output
- **WHEN** a position-management recipe is created
- **THEN** the router does not replace protection, issue a close command, apply a phase transition, or mutate state

### Requirement: Engine calculation results bind through local synchronous context
The router SHALL associate each calculation-only Engine response with the exact
`PositionResolvedStrategyInstance` that initiated the scalar synchronous call.

#### Scenario: Bind live-entry result locally
- **WHEN** live-entry projection returns `desired_entry: DesiredEntry | null`
- **THEN** the router creates a projected object whose source is the same input Runtime instance
- **AND** no Engine response identity field is required

#### Scenario: Bind open-trade result locally
- **WHEN** open-trade projection returns its calculation objects
- **THEN** the router creates a projected object whose source is the same input Runtime instance
- **AND** no Engine response identity field is required

### Requirement: Cleaned Engine response DTOs reject obsolete echoes
Runtime Engine response DTOs SHALL accept only their calculation-result fields.

#### Scenario: Reject an old live-entry response
- **WHEN** a live-entry response contains strategy, instance, market, timeframe, or target-bar echo fields
- **THEN** strict DTO construction rejects the response as containing unknown fields

#### Scenario: Reject an old open-trade response
- **WHEN** an open-trade response contains strategy, instance, market, timeframe, or target-bar echo fields
- **THEN** strict DTO construction rejects the response as containing unknown fields

### Requirement: Engine transport failures remain distinct
The Engine adapter boundary SHALL classify network, timeout, HTTP, and transport
failures as `StrategyEngineProjectionUnavailable`, and the router SHALL
propagate that failure.

#### Scenario: Live-entry transport is unavailable
- **WHEN** the live-entry Engine port raises `StrategyEngineProjectionUnavailable`
- **THEN** the router propagates it without fabricating a desired entry

#### Scenario: Open-trade transport is unavailable
- **WHEN** the open-trade Engine port raises `StrategyEngineProjectionUnavailable`
- **THEN** the router propagates it without fabricating a management recipe

#### Scenario: Programming error is not masked
- **WHEN** an Engine port raises an unexpected programming exception
- **THEN** the router does not relabel it as transport unavailability
