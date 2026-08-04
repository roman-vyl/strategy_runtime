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

### Requirement: Resolver performs a trade-cycle-conditional ABI lookup
The resolver SHALL call ABI only when `state.current_trade_cycle` is
present, using its exact `trade_cycle_id`; when `state.current_trade_cycle`
is absent, the resolver SHALL NOT call ABI and SHALL return a local closed
result instead.

#### Scenario: Skip the ABI call with no current trade cycle
- **WHEN** the resolver processes a state whose `current_trade_cycle` is
  `None`
- **THEN** it does not invoke the ABI lookup port
- **AND** it returns `PositionResolvedStrategyInstanceRuntimeState` with
  `position_open=False` and no fill facts, enabling live-entry routing

#### Scenario: Call ABI with the existing trade cycle
- **WHEN** the resolver processes a state whose `current_trade_cycle` is
  present
- **THEN** it copies the state's `strategy_instance_id` and
  `current_trade_cycle.trade_cycle_id` into the lookup request
- **AND** invokes the ABI lookup port exactly once with that pair

#### Scenario: This is a Live V1 in-memory lifecycle assumption, not a restart-safety proof
- **WHEN** `current_trade_cycle` is absent because Runtime has genuinely
  never applied an entry package for this strategy instance
- **THEN** skipping the ABI call and resolving `position_open=False` is
  correct, because no ABI-side record could exist under this contract
  without a prior Runtime-issued entry-package PUT
- **AND** this scenario is indistinguishable, by this capability alone, from
  Runtime having restarted and lost a previously acknowledged
  `current_trade_cycle` — restart-safe recovery of a lost trade cycle is
  explicitly out of scope for this capability and remains a future durable
  -state change (see `runtime-durable-state-repository-backlog.md`); this
  capability makes no claim of safe continuation after a Runtime restart

### Requirement: Resolver treats an ABI-reported trade-cycle-binding divergence as a fail-closed failure
When the resolver calls ABI with an existing `trade_cycle_id` and ABI
responds that the pair is unregistered, the resolver SHALL treat this as a
Runtime/ABI state divergence and SHALL NOT resolve it to `position_open:
false` or any other synthesized position fact.

#### Scenario: Propagate an unknown_trade_cycle_binding response
- **WHEN** ABI returns a documented `unknown_trade_cycle_binding` public
  error for a `trade_cycle_id` the resolver's input state believes is
  registered
- **THEN** the resolver lets the typed `OpenPositionLookupPublicError`
  propagate unchanged
- **AND** does not fabricate a closed or open position fact
- **AND** does not retry, fall back to a local closed result, or suppress
  the divergence

### Requirement: ABI response contains strict current-position facts
`OpenPositionLookupResponse` SHALL contain an exact boolean `position_open`
and the fill timestamp and average entry price required by the reported
state.

#### Scenario: Reject non-boolean position values
- **WHEN** `position_open` is integer `0`, integer `1`, a string, or null
- **THEN** the response is rejected as invalid

#### Scenario: Resolve no open position
- **WHEN** `position_open` is `false`
- **THEN** `first_fill_at_ms` and `average_entry_price` are absent

#### Scenario: Resolve an open position
- **WHEN** `position_open` is `true`
- **THEN** a strictly positive `first_fill_at_ms` and a positive
  `average_entry_price` are required
- **AND** the price is preserved as normalized decimal text without
  binary-float conversion

#### Scenario: Reject contradictory facts
- **WHEN** an open response omits either fill fact or a closed response
  includes one
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
