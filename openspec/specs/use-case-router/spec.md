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
Engine's `plans_by_side` calculation as one typed recipe.

#### Scenario: Map the live-entry request
- **WHEN** a closed position is routed
- **THEN** the request contains deployment strategy ID, raw spec, ticker, and base timeframe
- **AND** contains the committed bar open time as `target_bar_open_time_ms`
- **AND** does not contain Runtime `strategy_instance_id` or Engine `instance_id`

#### Scenario: Preserve the entry recipe
- **WHEN** Engine returns a valid `plans_by_side` response
- **THEN** the projection's long plan comes from the `long` mapping entry
- **AND** its short plan comes from the `short` mapping entry
- **AND** absent or null side entries remain null
- **AND** the source processing item is retained

### Requirement: Open-trade mapping requires frozen entry context
The router SHALL call open-trade projection only when the runtime state and
resolved facts contain complete immutable entry context, and it SHALL NOT send
Runtime-owned instance identity to Engine.

#### Scenario: Reject missing context before Engine
- **WHEN** the current trade cycle is absent, its entry recipe is not frozen, or either execution fact is absent
- **THEN** the router raises `OpenTradeContextUnavailable`
- **AND** does not call either Engine port

#### Scenario: Map the open-trade request
- **WHEN** an open position has complete context
- **THEN** the request contains strategy ID, raw spec, market, base timeframe, and target bar
- **AND** contains the frozen entry recipe
- **AND** contains resolver-supplied entry bar and executed entry price
- **AND** contains no Runtime strategy-instance ID, Runtime cycle ID, or exchange identifier

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
- **WHEN** live-entry projection returns `plans_by_side`
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
- **THEN** the router propagates it without fabricating an entry recipe

#### Scenario: Open-trade transport is unavailable
- **WHEN** the open-trade Engine port raises `StrategyEngineProjectionUnavailable`
- **THEN** the router propagates it without fabricating a management recipe

#### Scenario: Programming error is not masked
- **WHEN** an Engine port raises an unexpected programming exception
- **THEN** the router does not relabel it as transport unavailability
