# Runtime state and lifecycle plan

Status: current state and lifecycle design. Domain models, the repository port,
in-memory `get_or_create`, position resolution, and Engine projection are
implemented. State-transition application and physical persistence remain open.

## 1. Aggregate ownership

Runtime owns one logical long-lived aggregate for each active deployed strategy
instance:

```text
StrategyInstanceRuntimeState
```

The aggregate is not a single trade. It is the long-lived operating state of a
strategy deployment and remains after individual trades close.

Logical ownership does not require a particular physical store. The current
implementation is in-memory. SQLite or another durable repository remains an
architecture decision rather than an assumption embedded in the aggregate.

## 2. Stable identity

`strategy_instance_id` is the repository key. The deployment catalog derives it
once from:

```text
strategy_id
+ ticker
+ base_timeframe
+ raw_spec
```

The derived value is carried by `DeploymentSpecification` and
`StrategyBarProcessingUnit`.

The following are not repository keys:

- `strategy_id` — multiple instances may use the same strategy family;
- `trade_cycle_id` — each instance may complete many sequential cycles.

## 3. Initial aggregate

The implemented repository `get_or_create` produces:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
└── current_trade_cycle = null
```

The registered snapshot preserves the creation-time instrument, base timeframe,
opaque `raw_spec`, and source path.

Creation does not imply that Engine has produced a plan or ABI has opened a
position.

The current in-memory repository returns the same aggregate for repeated lookup
of the same identity and rejects a collision where the same
`strategy_instance_id` is associated with another `strategy_id`.

## 4. Nested trade cycle

`CurrentTradeCycle` is implemented as a state model, but the current semantic
projection contour does not create or update it. A future state-transition step
will create a cycle after accepting a live-entry projection according to the
final lifecycle policy.

Current implemented shape:

```text
CurrentTradeCycle
├── trade_cycle_id
├── desired_entry: DesiredEntry
├── desired_entry_frozen
└── position_management_recipe | null
```

Open-position facts resolved from ABI are currently transient and are not fields
of `CurrentTradeCycle`.

A strategy instance can have at most one current cycle in the active aggregate.
The creation policy, recipe revision semantics, and completed-cycle archival
policy are not yet implemented.

## 5. Desired-entry lifecycle

Each successful live-entry projection currently returns one complete
`desired_entry: DesiredEntry | null` inside
`LiveEntryProjectedStrategyInstance`. It does not mutate the repository, choose
a side, or arbitrate between plans.

Before execution:

```text
desired_entry_frozen = false
```

The future state applier will use these complete-snapshot semantics:

```text
no existing cycle
-> create cycle with the complete DesiredEntry after successful application

existing mutable desired entry
-> compare new and currently applied singular objects, then replace the complete snapshot

existing frozen desired entry
-> replacement forbidden
```

Top-level `desired_entry = null` is data and means that no entry is currently
desired. In the future reconciliation stage it cancels an acknowledged unfilled
entry or remains a no-op when none is applied. The current `CurrentTradeCycle`
model requires one `DesiredEntry`; absence of a cycle represents the state
before a desired entry has been successfully applied.

## 6. Execution and freeze transition

When ABI later confirms that a correlated entry instruction executed, a future
Runtime transition must:

1. identify the correct current trade cycle and exact accepted `DesiredEntry`;
2. freeze an executed entry context that references exactly that one object;
3. store `entry_bar_open_time_ms`;
4. store exact decimal `executed_entry_price`;
5. mark the cycle as owning an open position according to the final state model.

The concrete callback contract, instruction correlation, and required atomicity
depend on the future Runtime ↔ ABI execution boundary and remain an
implementation gate.

## 7. Open-position facts

The implemented closed-bar resolver returns transient facts for routing:

```text
position_open
entry_bar_open_time_ms
executed_entry_price
```

The resolver does not persist these facts. A later transition/applier stage will
decide whether and how they affect the aggregate.

The ABI lookup does not return Runtime readiness states, recipe data, order IDs,
fill IDs, exchange trade IDs, or a new correlation ID.

## 8. Position management recipe lifecycle

For an open position, each successful Engine open-trade response currently
returns:

```text
OpenTradeProjectedStrategyInstance
└── PositionManagementRecipe
    ├── desired_protection
    ├── close_signal
    └── diagnostics
```

This is a complete immutable projection snapshot. Runtime does not interpret it
during the routing/projection stage and does not currently persist it.

The future state applier will replace the complete previous management recipe.
Replacement semantics preserve explicit false/null values and never merge with
the previous recipe.

## 9. Closure and reuse of the aggregate

After a future closure transition, the current cycle reaches a completed state:

```text
current trade cycle -> completed
```

The completed cycle may be archived or journaled, while:

```text
strategy_instance_id = unchanged
```

The aggregate returns to a state capable of starting a new trade cycle. A new
cycle receives a new `trade_cycle_id`. None of these transitions is implemented
in the current projection contour.

## 10. Live V1 persistence and concurrency boundary

The repository port intentionally does not expose a storage technology. The
current implementation is an in-memory dictionary protected by `RLock`.

The initial live deployment is constrained to one Runtime process and one
worker. Multiple replicas and horizontal scaling are prohibited. A single
process-local keyed mutex per `strategy_instance_id` serializes both closed-bar
reconciliation and ABI fill-webhook mutations across their complete
`load → decision → ABI call → state update → save` cycle. Different strategy
instances may proceed in parallel.

A webhook that waits behind reconciliation must reload state after acquiring
the mutex. Holding the mutex across an ABI call is accepted for Live V1, so
every such call requires a bounded timeout. An ambiguous create/replace result
must not be retried blindly.

Independent of storage choice, state application must not partially merge a
`DesiredEntry`, and `get_or_create` must remain deterministic and identity-safe.
The repository's own `RLock` does not replace the end-to-end keyed mutex.

Repository revisions/CAS, persisted pending execution actions, ABI command
idempotency, idempotent fill-event application, restart recovery, and
multi-worker or multi-replica deployment remain deferred. They are required
before horizontal scaling or stronger production guarantees. The Live V1
boundary is intentionally limited and is not the final production-scale
concurrency model.

## 11. Identifier boundary

The state model uses only:

```text
strategy_id
strategy_instance_id
trade_cycle_id
```

`trade_cycle_id` remains internal to Runtime and is not sent to Strategy Engine.
No Engine `trade_id`, recipe revision ID, configuration hash, market-data hash,
payload contract version, flow ID, or trace ID belongs in the aggregate.

A future `command_id` may be introduced only if the asynchronous Runtime ↔ ABI
execution contract proves that an independently durable command identity is
required.
