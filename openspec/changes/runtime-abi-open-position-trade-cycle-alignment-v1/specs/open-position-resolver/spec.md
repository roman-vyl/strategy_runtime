## REMOVED Requirements

### Requirement: Resolver performs one identity-only ABI lookup
**Reason**: The authoritative ABI open-position contract
(`abi-open-position-lookup-api-v1`, ABI commit
`ea5a18903f28d89f5f97a6b9a8c82ae395bf720a`) is pair-addressed by
`(strategy_instance_id, trade_cycle_id)`, not identity-only. ABI's
`EntryPackageCorrelationRepository` only ever learns a `trade_cycle_id` via
the entry-package PUT route Runtime itself sends during reconciliation; ABI
explicitly does not support a `strategy_instance_id`-only lookup, and treats
an unregistered pair as a fail-closed `422 unknown_trade_cycle_binding`,
never as `position_open: false`. An unconditional identity-only lookup can no
longer be issued once `current_trade_cycle` is absent, because no
`trade_cycle_id` exists yet to place in the request.
**Migration**: See the new "Resolver performs a trade-cycle-conditional ABI
lookup" requirement below. Callers of `OpenPositionResolver.resolve(state)`
are unaffected — the signature and return shape are unchanged; only the
resolver's internal decision of whether and how to call ABI changes.

## ADDED Requirements

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

## MODIFIED Requirements

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
