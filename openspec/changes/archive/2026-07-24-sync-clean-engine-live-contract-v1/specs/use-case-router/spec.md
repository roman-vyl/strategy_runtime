## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Live-entry mapping and result are exact
The router SHALL build the live-entry request from the current processing unit
without transmitting Runtime-owned instance identity and SHALL preserve
Engine's singular `desired_entry` without side selection or arbitration.

#### Scenario: Map the live-entry request
- **WHEN** a closed position is routed
- **THEN** the request contains deployment strategy ID, raw spec, ticker, and base timeframe
- **AND** contains the committed bar open time as `target_bar_open_time_ms`
- **AND** does not contain Runtime `strategy_instance_id` or Engine `instance_id`

#### Scenario: Preserve the desired entry
- **WHEN** Engine returns a valid `desired_entry`
- **THEN** the projection contains that same singular value
- **AND** its embedded side is preserved without Runtime arbitration
- **AND** null remains null
- **AND** the source processing item is retained

### Requirement: Open-trade mapping requires frozen entry context
The router SHALL call open-trade projection only when the runtime state and
resolved facts contain complete immutable entry context, and it SHALL NOT send
Runtime-owned instance identity to Engine.

#### Scenario: Reject missing context before Engine
- **WHEN** the current trade cycle is absent, its desired entry is not frozen, or either execution fact is absent
- **THEN** the router raises `OpenTradeContextUnavailable`
- **AND** does not call either Engine port

#### Scenario: Map the open-trade request
- **WHEN** an open position has complete context
- **THEN** the request contains strategy ID, raw spec, market, base timeframe, and target bar
- **AND** contains the frozen `DesiredEntry`
- **AND** contains resolver-supplied entry bar and executed entry price
- **AND** contains no Runtime strategy-instance ID, Runtime cycle ID, or exchange identifier

## REMOVED Requirements

### Requirement: Engine response echoes are binding checks

**Reason:** The cleaned Engine live contract returns calculation results only,
and scalar synchronous Runtime context already binds the result to its source.

**Migration:** Remove `_validate_echo()`, `EngineResponseBindingError`, all echo
fields from response DTOs, and all echo-validation tests.
