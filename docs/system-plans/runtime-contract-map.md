# Runtime closed-bar contract map

Status: current implemented contract map for the semantic Engine-projection
pipeline. Production HTTP adapters and projection-result state application are
outside this map.

This map describes current implemented contracts only. The approved but not yet
implemented continuation from live-entry projection through ABI reconciliation
is defined by
[`runtime-abi-entry-reconciliation-master-plan.md`](runtime-abi-entry-reconciliation-master-plan.md).

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

`strategy_instance_id` remains internal to Runtime and ABI and does not cross
the Strategy Engine live-projection boundary.

No ID is introduced to correlate synchronous repository, resolver, router, or
Engine projection calls. Typed object containment, the scalar call stack, and
the source `PositionResolvedStrategyInstance` provide that association.

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
├── risk_multiplier
└── current_trade_cycle: CurrentTradeCycle | null

CurrentTradeCycle
├── trade_cycle_id
└── applied_entry_package: AppliedEntryPackage

AppliedEntryPackage
├── applied_desired_entry
└── calculated_quantity
```

Behavior:

- return the existing aggregate unchanged; or
- create and return a new aggregate with canonical Runtime-owned
  `risk_multiplier = "1"` and `current_trade_cycle = null`;
- keep that field out of deployment, the registration request,
  `registered_spec_snapshot`, `raw_spec`, and identity derivation;
- reject reuse of one `strategy_instance_id` for another `strategy_id`.

`current_trade_cycle = null` means only that Runtime owns no current cycle or
acknowledged entry package. ABI lookup remains authoritative for exchange
position facts.

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
position without a complete applied entry package fails closed.

## 7. Live-entry projection contract

Request sent to the Engine port:

```text
LiveEntryProjectionRequest
├── strategy_id
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
└── desired_entry: DesiredEntry | null

DesiredEntry
├── side: long | short
├── source_plan_bar_open_time_ms
├── planned_entry_price
├── initial_stop_price
├── initial_take_price
└── locked_exit_profile
```

`initial_take_price` is required canonical positive exact-decimal text. The
desired entry may be absent, but an existing object cannot omit take or carry a
null, empty, non-finite, zero, or negative take. Malformed objects fail before projected
Runtime state is created.

The scalar router binds the calculation to its existing local source and
returns:

```text
LiveEntryProjectedStrategyInstance
├── source
└── desired_entry: DesiredEntry | null
```

The router passes through the singular result without side selection,
arbitration, or side-specific storage and does not apply it to repository state.

## 8. Open-trade projection contract

Open-trade is allowed only when:

```text
position_open = true
current_trade_cycle exists
applied_entry_package exists
entry_bar_open_time_ms exists
executed_entry_price exists
```

Request sent to the Engine port:

```text
OpenTradeProjectionRequest
├── strategy_id
├── raw_spec
├── ticker
├── base_timeframe
├── target_bar_open_time_ms
├── desired_entry: DesiredEntry
└── entry_bar_open_time_ms
```

The request contains no `trade_id` and no `trade_cycle_id`. The Runtime cycle
identity is not required by the synchronous Engine calculation and remains
inside `CurrentTradeCycle`.

Strategy Engine v1 calculates position management from the applied desired
entry's `planned_entry_price`. The resolver-supplied `executed_entry_price`
remains a Runtime/ABI execution fact and an open-position invariant, but it
does not cross the Runtime → Engine boundary.

Engine port response:

```text
OpenTradeProjectionResponse
├── desired_protection
├── close_signal
└── diagnostics
```

The scalar router binds the calculation to its existing local source and
returns:

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

## 9. Engine calculation-result binding

Both Engine paths are scalar and synchronous:

```text
PositionResolvedStrategyInstance
→ Engine call
→ calculation-only response
→ projected object retaining the same source
```

Engine responses contain no strategy, instance, market, timeframe, or
target-bar echoes. Strict DTO decoding rejects the obsolete echo-bearing shape.
Runtime's pre-call identity-chain validation remains responsible for binding the
processing unit, deployment, and runtime state before Engine is invoked.

## 10. Removed and prohibited contract fields

The Runtime projection contracts contain none of the former identifier and
provenance zoo:

- no `stable_deployment_id`;
- no manually supplied deployment `strategy_instance_id`;
- no Runtime `strategy_instance_id` or `instance_id` sent to Engine;
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

`EntryReconciliationOrchestrator` is already implemented. It receives only one
`LiveEntryProjectedStrategyInstance` and extracts its exact source state from
the embedded projection provenance:

```text
projection.source.resolved_state.runtime_state
```

The current stopping point remains the typed semantic projection contour; the
complete closed-bar orchestration is not implemented yet. The next seam extends
the same `StrategyRuntimeOrchestrator.process(...)` invocation so that it
acquires the per-instance keyed mutex before loading state and retains it
through ABI position lookup, Engine projection, typed branching, invocation of
the existing nested orchestrator, and repository save.

For `LiveEntryProjectedStrategyInstance`,
`StrategyRuntimeOrchestrator` will call
`EntryReconciliationOrchestrator.execute(projection)` under the caller-owned
mutex and save replacement state when required. The nested operation accepts no
separate aggregate argument and does not acquire the mutex, reload state, or
save independently.

For `OpenTradeProjectedStrategyInstance`,
`StrategyRuntimeOrchestrator.process(unit)` will fail explicitly until the
position-management branch is separately designed. The handoff must not record
or report that dispatch as successful.
