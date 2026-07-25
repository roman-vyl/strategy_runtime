## ADDED Requirements

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
and preserve singular `desired_entry: DesiredEntry | null` without side
selection or arbitration.

#### Scenario: Map the live-entry request
- **WHEN** a closed position is routed
- **THEN** the request contains deployment strategy ID, raw spec, ticker, and base timeframe
- **AND** contains the derived instance ID
- **AND** contains the committed bar open time as `target_bar_open_time_ms`

#### Scenario: Preserve the desired entry
- **WHEN** Engine returns a valid live-entry response
- **THEN** the projection contains the returned singular `DesiredEntry`
- **AND** its embedded side is preserved without Runtime arbitration
- **AND** null remains null
- **AND** the source processing item is retained

### Requirement: Open-trade mapping requires frozen entry context
The router SHALL call open-trade projection only when the runtime state and
resolved facts contain complete immutable entry context.

#### Scenario: Reject missing context before Engine
- **WHEN** the current trade cycle is absent, its desired entry is not frozen, or either execution fact is absent
- **THEN** the router raises `OpenTradeContextUnavailable`
- **AND** does not call either Engine port

#### Scenario: Map the open-trade request
- **WHEN** an open position has complete context
- **THEN** the request contains the same strategy, instance, market, and target-bar mapping as live entry
- **AND** contains the frozen `DesiredEntry`
- **AND** contains resolver-supplied entry bar and executed entry price
- **AND** contains no Runtime cycle ID or exchange identifier

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

### Requirement: Engine response echoes are binding checks
The router SHALL validate strategy ID, instance ID, ticker, base timeframe, and
target bar echoed by either Engine projection.

#### Scenario: Reject any echo mismatch
- **WHEN** any required echo differs from the corresponding request value
- **THEN** the router raises `EngineResponseBindingError`
- **AND** does not return a fabricated recipe

#### Scenario: Do not duplicate echoes in recipes
- **WHEN** all echoes are valid
- **THEN** the router does not copy them into `DesiredEntry` or `PositionManagementRecipe`

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
