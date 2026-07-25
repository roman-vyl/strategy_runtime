# Strategy Runtime master plan

Status: current architecture and implementation roadmap for Strategy Runtime.

## 1. Current implemented foundation

The utility closed-bar contour is implemented and verified:

```text
MDS closed-bar webhook
-> FilesystemDeploymentCatalog
-> CommittedBarDeploymentSelector
-> CommittedBarOrchestrator fan-out
-> StrategyCycleHandoffBoundary
-> stop
```

Its output is one immutable `StrategyBarProcessingUnit` per selected enabled strategy deployment. The unit contains only:

- the selected deployment specification;
- the committed bar identity;
- the complete Runtime deployment envelope: strategy semantics, ticker, and base timeframe; utility derives the stable `strategy_instance_id` from this immutable content.

The utility contour owns no position state, recipe state, Engine use-case selection, ABI lifecycle, or trade management.

Activation is not a separate persisted subsystem. Every Runtime deployment JSON contains a required boolean `enabled` field. The field is operational metadata, does not participate in derived `strategy_instance_id`, and is evaluated directly by deployment selection. Changing only `enabled` preserves identity; changing strategy semantics, ticker, or base timeframe creates a new identity.

## 2. Implemented semantic projection contour

The semantic Runtime core is implemented behind the utility handoff boundary. It
processes one `StrategyBarProcessingUnit` at a time:

```text
StrategyBarProcessingUnit
-> StrategyRuntimeOrchestrator
-> StrategyInstanceRuntimeStateRepository.get_or_create
-> OpenPositionResolver
-> UseCaseRouter
-> Strategy Engine projection port
-> LiveEntryProjectedStrategyInstance
   or OpenTradeProjectedStrategyInstance
-> back to StrategyRuntimeOrchestrator
-> stop
```

The following semantic components are implemented and tested:

- `StrategyRuntimeOrchestrator`;
- `StrategyInstanceRuntimeStateRepository` port and in-memory implementation;
- `OpenPositionResolver`;
- `StrategyUseCaseRouter`;
- typed live-entry and open-trade Engine requests and responses;
- immutable desired-entry and position-management projection objects;
- strict calculation-only Engine response DTOs bound through local synchronous
  call context.

The orchestrator remains the coordinator. Each submodule returns to the same
orchestration method and does not independently advance the pipeline.

The production bootstrap does not yet attach this semantic core to the utility
handoff by default. That wiring decision does not change the implemented
semantic boundary: the core is independently callable and the handoff accepts a
downstream sink.

## 3. Runtime state ownership

Runtime owns the logical long-lived state of every strategy instance. The
application boundary is stateful even though the physical persistence policy is
not yet fixed.

The primary aggregate is:

```text
StrategyInstanceRuntimeState
```

Its stable key is:

```text
strategy_instance_id = utility-derived identity of strategy semantics + ticker + base timeframe
```

The aggregate survives multiple entry, open-position, close, and re-entry cycles. A completed trade does not destroy or replace the long-lived strategy-instance aggregate.

The current repository implementation is in-memory and protected by an
in-process lock. Keeping the initial Runtime in-memory is an accepted option.
SQLite or another durable store is not assumed by the domain model and remains
an explicit architecture gate.

## 4. Identity hierarchy

The accepted identity hierarchy is:

```text
strategy_id
= strategy family/type

strategy_instance_id
= long-lived deployed instance and repository key

trade_cycle_id
= one nested planning -> entry -> management -> close lifecycle
```

One `strategy_instance_id` may own many sequential `trade_cycle_id` values over its lifetime.

Runtime keeps `trade_cycle_id` internal and sends no trade identifier to Strategy
Engine. Engine-side `trade_id` removal is tracked by external cleanup plan 24.
It must be removed without replacement by `trade_cycle_id`.

## 5. Implemented projection pipeline

The current semantic pipeline obtains state and transient position facts, then
returns a typed Engine projection. It does not yet apply the projection back to
the aggregate.

### 5.1 Repository stage

`get_or_create` guarantees one state object exists for the active strategy
instance during the lifetime of the repository implementation.

A newly created instance contains identity and registered specification provenance, but:

```text
current_trade_cycle = null
```

It has no recipe, position facts, or management projection yet.

### 5.2 Open-position resolution stage

The resolver queries ABI once per active instance using only `strategy_instance_id` and returns transient facts:

```text
position_open
entry_bar_open_time_ms
executed_entry_price
```

It does not persist them and does not mutate either recipe.

### 5.3 Engine use-case routing and projection stage

```text
position_open = false
-> Strategy Engine live-entry projection

position_open = true
-> Strategy Engine open-trade projection
```

The router does not interpret the strategy result into ABI commands.

For the live-entry path, the Engine port returns
`LiveEntryProjectionResponse` containing only `desired_entry`. Runtime binds
that calculation to the exact source object held by the scalar call and returns:

```text
LiveEntryProjectedStrategyInstance
└── desired_entry: DesiredEntry | null
```

`DesiredEntry.side` is already `long` or `short`. Runtime does not arbitrate
between sides and never receives or stores two side-specific plans.

For the open-trade path, the Engine port returns
`OpenTradeProjectionResponse` containing only desired protection, close signal,
and diagnostics. Runtime binds that calculation to the same local source object
and returns:

```text
OpenTradeProjectedStrategyInstance
└── PositionManagementRecipe
    ├── desired_protection
    ├── close_signal
    └── diagnostics
```

The open-trade Engine request carries the frozen `DesiredEntry` and
`entry_bar_open_time_ms`. Engine v1 uses its `planned_entry_price` for
position-management calculation. ABI-supplied `executed_entry_price` remains a
Runtime execution fact and is not transmitted to Engine.

These projected objects are the terminal result of the currently implemented
semantic contour.

## 6. Projection objects and future state application

The semantic projection contour defines two distinct immutable projection objects.
Their lifecycle application is the responsibility of a future state-transition
stage.

### DesiredEntry

Produced as the complete singular live-entry desire:

```text
desired_entry: DesiredEntry | null
```

`DesiredEntry` contains `side`, provenance, mandatory entry, stop, and take
prices, and the locked exit profile.
`initial_take_price` is canonical positive exact-decimal text; missing, null,
empty, non-finite, zero, or negative values fail closed at `DesiredEntry`
construction.

When the future state applier accepts this projection, the new `desired_entry`
replaces the complete mutable desired snapshot. A returned `null` explicitly
clears a previously applied desired entry.

`desired_entry_frozen` is Runtime-owned lifecycle metadata stored beside the
singular object in the current placeholder cycle model. Once the executed entry
context is frozen, its referenced `DesiredEntry` cannot be replaced. The
transition that creates and freezes execution state is not part of the
implemented projection contour.

### PositionManagementRecipe

Produced as a complete open-trade projection:

```text
PositionManagementRecipe
├── desired_protection
├── close_signal
└── diagnostics
```

The router returns the recipe without interpretation. When a future state
applier is implemented, every accepted open-trade response will replace the
complete prior management recipe, including explicit `false` and `null` values.

## 7. Engine contract policy

Both Engine request paths retain:

- strategy identity;
- `raw_spec`;
- market ticker and base timeframe;
- exact `target_bar_open_time_ms`.

The target bar is required for deterministic calculation against the exact committed-bar event.

Runtime-owned `strategy_instance_id` does not cross the Engine boundary.
Live-entry response contains only `desired_entry: DesiredEntry | null`;
open-trade response contains
only desired protection, close signal, and diagnostics. Old responses carrying
identity, market, timeframe, or target-bar echoes are rejected by strict DTO
decoding.

No specification, deployment, source-configuration, or market-data hash crosses the Runtime ↔ Engine boundary.

The Runtime business-identity set is deliberately small:

```text
strategy_id
strategy_instance_id
trade_cycle_id
```

`target_bar_open_time_ms`, `source_plan_bar_open_time_ms`, and
`entry_bar_open_time_ms` are temporal coordinates, not business identities.

Runtime does not add IDs or hashes merely to correlate synchronous enrichment
stages. The scalar call stack and the source
`PositionResolvedStrategyInstance` preserve that association.

The following fields are removed from, or prohibited at, the Runtime ↔ Engine
boundary:

- `stable_deployment_id`;
- `trade_id`;
- `strategy_version`;
- `compatibility_profile`;
- payload-level `contract_version`;
- `source_config_hash`, `spec_revision_hash`, and deployment-revision hashes;
- `market_data_hash`;
- flow or trace identifiers used as business correlation.

The corresponding Strategy Engine repository cleanup is tracked by external
plans 24–29.

## 8. Current stopping point

The implemented semantic contour stops after producing one validated:

```text
LiveEntryProjectedStrategyInstance
```

or:

```text
OpenTradeProjectedStrategyInstance
```

It deliberately does not:

- mutate `StrategyInstanceRuntimeState`;
- create, replace, freeze, close, or archive a trade cycle;
- persist entry or position-management recipes;
- construct ABI execution commands;
- call ABI execution endpoints;
- interpret Engine calculations as exchange operations.

## 9. Open architecture gates

1. Decide whether the initial Runtime remains in-memory or adopts SQLite or
   another durable state adapter.
2. Define state-result application and repository update semantics.
3. Define when `trade_cycle_id` is created and how a cycle is completed.
4. Define the ABI execution notification/callback path that freezes the exact
   accepted `DesiredEntry` with its execution facts.
5. Decide whether the future asynchronous Runtime ↔ ABI command boundary needs
   one Runtime-owned `command_id`; do not introduce one before that boundary
   proves it necessary.
6. Apply Engine cleanup plans 24–29 before production HTTP integration.
7. Implement and verify production ABI and Strategy Engine adapters.
8. Define concurrency, idempotency, restart, and recovery guarantees appropriate
   to the selected persistence model.

## 10. Next implementation sequence

1. Specify and implement the projection-result state applier.
2. Decide the repository persistence policy and implement only the guarantees
   required by that decision.
3. Design the ABI execution callback and singular desired-entry freeze transition.
4. Design closure transition, completed-cycle archival, and next-cycle creation.
5. Extend processing journal events around semantic Runtime stages.
6. Add full integration tests across utility Runtime, state repository, fake
   ABI, and fake Engine.
7. Add production HTTP adapters only after the adjacent service contracts match
   the cleaned Runtime boundary.
