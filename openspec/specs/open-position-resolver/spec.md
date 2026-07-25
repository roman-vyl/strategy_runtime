# open-position-resolver Specification

## Purpose

Define the scalar semantic Runtime boundary that resolves authoritative current
open-position facts for one strategy-instance state through an identity-only ABI
lookup.

## Requirements

### Requirement: Runtime resolves one state after get-or-create
Strategy Runtime SHALL provide a scalar `OpenPositionResolver` invoked by
`StrategyRuntimeOrchestrator` after repository get-or-create.

#### Scenario: Resolve one current state
- **WHEN** the orchestrator obtains one `StrategyInstanceRuntimeState`
- **THEN** it invokes the resolver once with that state
- **AND** receives one `PositionResolvedStrategyInstanceRuntimeState`

#### Scenario: Keep downstream behavior outside the resolver
- **WHEN** the resolver returns
- **THEN** it has not called the use-case router or Strategy Engine
- **AND** has not sent an execution instruction to ABI

### Requirement: Resolver performs one identity-only ABI lookup
The resolver SHALL perform exactly one ABI lookup for its input state without
filtering by local lifecycle condition.

#### Scenario: Build the narrow request
- **WHEN** the resolver processes a state
- **THEN** it copies only the state's `strategy_instance_id` into the lookup request
- **AND** invokes the ABI lookup port exactly once

#### Scenario: Ignore local desired-entry state as a filter
- **WHEN** the state has no trade cycle, an applied desired entry, or frozen entry context
- **THEN** the resolver still performs the lookup

### Requirement: ABI response contains strict current-position facts
`OpenPositionLookupResponse` SHALL contain an exact boolean `position_open` and
the entry bar and executed price required by the reported state.

#### Scenario: Reject non-boolean position values
- **WHEN** `position_open` is integer `0`, integer `1`, a string, or null
- **THEN** the response is rejected as invalid

#### Scenario: Resolve no open position
- **WHEN** `position_open` is `false`
- **THEN** entry bar and executed entry price are absent

#### Scenario: Resolve an open position
- **WHEN** `position_open` is `true`
- **THEN** a non-negative entry bar and executed entry price are required
- **AND** the price is preserved as normalized decimal text without binary-float conversion

#### Scenario: Reject contradictory facts
- **WHEN** an open response omits either execution fact or a closed response includes one
- **THEN** the response is rejected as invalid

### Requirement: Resolver enrichment is transient
The resolver SHALL return a view retaining the exact input aggregate and the
validated current-position facts.

#### Scenario: Return facts without state application
- **WHEN** lookup succeeds
- **THEN** the returned view references the input `StrategyInstanceRuntimeState`
- **AND** contains the validated position facts
- **AND** the repository-owned aggregate is not mutated or persisted

### Requirement: ABI failures remain typed and distinct
The ABI adapter boundary SHALL distinguish lookup availability failures from
protocol-invalid responses, and the resolver SHALL propagate those failures.

#### Scenario: Lookup is unavailable
- **WHEN** network, timeout, or HTTP transport prevents a lookup
- **THEN** the adapter raises `OpenPositionLookupUnavailable`
- **AND** the resolver does not fabricate a closed position

#### Scenario: Lookup response violates protocol
- **WHEN** JSON, field presence, field types, or response combinations are invalid
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** the resolver does not fabricate a position fact

#### Scenario: Programming error is not masked
- **WHEN** the lookup port raises an unexpected programming exception
- **THEN** the resolver does not relabel it as lookup unavailability
