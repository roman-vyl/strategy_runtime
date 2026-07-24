# Runtime closed-bar contract map

Status: current implemented contract map for the semantic Engine-projection
pipeline. Production HTTP adapters and projection-result state application are
outside this map.

## 1. Invocation and cardinality

The utility orchestrator fans one committed bar out into independently
dispatched units. The semantic orchestrator processes one unit per invocation:

```text
CommittedBarOrchestrator
-> StrategyCycleHandoffBoundary
-> StrategyRuntimeOrchestrator.process(unit)
```

The semantic submodule ports use tuple/sequence contracts where useful, but the
current orchestrator passes one state and receives one projected result for each
`StrategyBarProcessingUnit`.

## 2. Utility handoff

Input:

```text
StrategyBarProcessingUnit
├── strategy_instance_id
├── deployment: DeploymentSpecification
│   ├── strategy_instance_id
│   ├── enabled
│   ├── instrument
│   ├── base_timeframe
│   ├── strategy_id
│   ├── raw_spec
│   └── source_path
└── committed_bar: CommittedBarEvent
    ├── instrument
    ├── timeframe
    └── open_time_ms
```

The utility handoff contains no Runtime aggregate, recipe, ABI position state,
Engine result, flow ID, trace ID, hash, or transport version.

## 3. Identifier policy

The current business-identity hierarchy is:

```text
strategy_id
└── strategy_instance_id
    └── trade_cycle_id
```

- `strategy_id` identifies the strategy implementation/family.
- `strategy_instance_id` is derived once by the deployment catalog from
  `strategy_id + ticker + base_timeframe + raw_spec`.
- `trade_cycle_id` identifies one Runtime-owned entry-to-close cycle and remains
  internal to Runtime.

The Engine transport field `instance_id` is populated with the exact
`strategy_instance_id`. It is a field-name alias at the transport boundary, not
another identity.

No ID is introduced to correlate synchronous repository, resolver, router, or
Engine projection calls. Typed object containment and the current call stack
provide that association.

## 4. State repository contract

Caller:

```text
StrategyRuntimeOrchestrator
```

Callee:

```text
StrategyInstanceRuntimeStateRepository.get_or_create
```

Request:

```text
GetOrCreateStrategyInstanceRuntimeStateRequest
├── strategy_instance_id
├── strategy_id
├── instrument
├── base_timeframe
├── raw_spec
└── source_path
```

Response:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
└── current_trade_cycle
```

Behavior:

- return the existing aggregate unchanged; or
- create and return a new aggregate with `current_trade_cycle = null`;
- reject reuse of one `strategy_instance_id` for another `strategy_id`.

The current implementation is in-memory and synchronized with `RLock`.
Durability is not part of this port contract.

## 5. Open-position resolver contract

Caller:

```text
StrategyRuntimeOrchestrator
```

Callee:

```text
OpenPositionResolver.resolve
```

For each supplied state, the resolver sends ABI only:

```text
OpenPositionLookupRequest
└── strategy_instance_id
```

ABI response:

```text
OpenPositionLookupResponse
├── position_open: bool
├── entry_bar_open_time_ms: int | null
└── executed_entry_price: exact decimal text | null
```

Validity rules:

- an open position requires both entry facts;
- a closed position carries neither entry fact;
- decimal price text is normalized without conversion through binary float.

Resolver output:

```text
PositionResolvedStrategyInstanceRuntimeState
├── runtime_state
├── position_open
├── entry_bar_open_time_ms
└── executed_entry_price
```

The resolver preserves item count, order, and identity. The current orchestrator
invokes it with a one-item tuple.

## 6. Use-case router input and decision

The router receives:

```text
PositionResolvedStrategyInstance
├── processing_unit
└── resolved_state
```

The processing unit supplies the deployment and exact committed target bar. The
resolved state supplies current ABI position facts.

Routing depends only on:

```text
position_open = false -> live-entry
position_open = true  -> open-trade
```

A newly created state with no current cycle is valid for live-entry. An open
position without a complete frozen entry context fails closed.

## 7. Live-entry projection contract

Request sent to the Engine port:

```text
LiveEntryProjectionRequest
├── strategy_id
├── instance_id = strategy_instance_id
├── raw_spec
├── ticker
├── base_timeframe
└── target_bar_open_time_ms
```

`target_bar_open_time_ms` is copied from the current committed-bar event and
binds the synchronous projection to one exact bar.

Engine port response:

```text
LiveEntryProjectionResponse
├── strategy_id
├── instance_id
├── ticker
├── base_timeframe
├── target_bar_open_time_ms
├── long_plan
└── short_plan
```

After echo validation, the router returns:

```text
LiveEntryProjectedStrategyInstance
├── source
└── entry_recipe
    ├── long_plan
    └── short_plan
```

A side may be `null`; both sides may be `null`. The router creates a complete
`EntryRecipe` object but does not apply it to repository state.

## 8. Open-trade projection contract

Open-trade is allowed only when:

```text
position_open = true
current_trade_cycle exists
entry_recipe_frozen = true
entry_bar_open_time_ms exists
executed_entry_price exists
```

Request sent to the Engine port:

```text
OpenTradeProjectionRequest
├── strategy_id
├── instance_id = strategy_instance_id
├── raw_spec
├── ticker
├── base_timeframe
├── target_bar_open_time_ms
├── entry_recipe
├── entry_bar_open_time_ms
└── executed_entry_price
```

The request contains no `trade_id` and no `trade_cycle_id`. The Runtime cycle
identity is not required by the synchronous Engine calculation and remains
inside `CurrentTradeCycle`.

Engine port response:

```text
OpenTradeProjectionResponse
├── strategy_id
├── instance_id
├── ticker
├── base_timeframe
├── target_bar_open_time_ms
├── desired_protection
├── close_signal
└── diagnostics
```

After echo validation, the router returns:

```text
OpenTradeProjectedStrategyInstance
├── source
└── position_management_recipe
    ├── desired_protection
    ├── close_signal
    └── diagnostics
```

The router copies Engine-owned calculation output without interpreting or
persisting it.

## 9. Engine response binding

For both Engine paths, Runtime compares:

- `strategy_id`;
- `instance_id`;
- `ticker`;
- `base_timeframe`;
- `target_bar_open_time_ms`.

Every field must equal the originating request. A mismatch raises
`EngineResponseBindingError`.

Echo fields validate the synchronous response. They are not copied into recipes,
used to locate source objects, or treated as additional correlation IDs.

## 10. Removed and prohibited contract fields

The Runtime projection contracts contain none of the former identifier and
provenance zoo:

- no `stable_deployment_id`;
- no manually supplied deployment `strategy_instance_id`;
- no Engine `trade_id`;
- no Engine-bound `trade_cycle_id`;
- no `strategy_version` or `compatibility_profile`;
- no payload `contract_version`;
- no `source_config_hash`, `spec_revision_hash`, or deployment revision hash;
- no `market_data_hash`;
- no `flow_id` or propagated `trace_id`;
- no recipe or projection correlation ID.

External Engine cleanup plans 24–29 remove the corresponding obsolete fields
from the adjacent Strategy Engine implementation. Runtime does not add
compatibility aliases while that cleanup is pending.

Temporal coordinates such as `target_bar_open_time_ms`,
`source_plan_bar_open_time_ms`, and `entry_bar_open_time_ms` remain because they
are calculation facts, not entity identities.

## 11. Semantic orchestrator output and stopping point

For each input unit, `StrategyRuntimeOrchestrator.process` returns exactly one:

```text
LiveEntryProjectedStrategyInstance
```

or:

```text
OpenTradeProjectedStrategyInstance
```

The current contour does not:

- persist the projected recipe;
- mutate the aggregate;
- create or freeze a trade cycle;
- create ABI commands;
- interpret protection or close signals;
- perform exchange reconciliation.

## 12. Planned next seam

After the projected object returns to `StrategyRuntimeOrchestrator`, a future
state-transition module will:

- accept or reject the projection under lifecycle invariants;
- apply complete recipe replacement semantics;
- update the repository according to the selected in-memory or durable
  persistence policy;
- later hand the uninterpreted recipe to separately designed ABI
  execution-command planning.
