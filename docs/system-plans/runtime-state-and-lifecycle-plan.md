# Runtime state and lifecycle plan

Status: current state and lifecycle design. Domain models, the repository port,
in-memory `get_or_create`, position resolution, Engine projection, pure entry
reconciliation, the nested `EntryReconciliationOrchestrator` application
operation, and the top-level closed-bar `StrategyRuntimeOrchestrator` critical
section are all implemented. Production adapter/composition wiring and
physical persistence policy remain open.

The implemented state model below remains authoritative for current code.
Closed-bar state application and the mutex-owned closed-bar writer are
implemented; production outbound adapters and composition remain pending (see
[`runtime-live-entry-production-integration-plan.md`](runtime-live-entry-production-integration-plan.md));
fill execution state and the fill writer remain pending (see
[`runtime-abi-entry-reconciliation-master-plan.md`](runtime-abi-entry-reconciliation-master-plan.md)
and `I5`).

## 1. Aggregate ownership

Runtime owns one logical long-lived aggregate for each active deployed strategy
instance:

```text
StrategyInstanceRuntimeState
```

The aggregate is not a single trade. It is the long-lived operating state of a
strategy deployment and remains after individual trades close.

Logical ownership does not require a particular physical store. The current
implementation is in-memory, and Live V1 retains that repository. SQLite or
another durable repository remains a future gate rather than an initial-launch
requirement or an assumption embedded in the aggregate.

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
├── risk_multiplier = "1"
└── current_trade_cycle = null
```

The registered snapshot preserves the creation-time instrument, base timeframe,
opaque `raw_spec`, and source path.

`risk_multiplier` is a Runtime-owned canonical field. It is not a deployment
field, registration-request field, `raw_spec` member, registered snapshot
field, or identity input. The repository supplies `"1"` when the aggregate is
first created. Repeated discovery returns the existing aggregate rather than
creating or resetting that state.

Creation does not imply that Engine has produced a plan or ABI has opened or
not opened a position. In particular, `current_trade_cycle = null` means only
that Runtime owns no current cycle or acknowledged entry package; ABI lookup
remains authoritative for exchange position facts.

The current in-memory repository returns the same aggregate for repeated lookup
of the same identity and rejects a collision where the same
`strategy_instance_id` is associated with another `strategy_id`.

## 4. Nested trade cycle

`CurrentTradeCycle` is implemented as a state model. The closed-bar
orchestration creates and updates it through `EntryReconciliationOrchestrator`
after accepting a live-entry projection and a successful (fake, pre-production)
ABI acknowledgement.

Current implemented shape:

```text
CurrentTradeCycle
├── trade_cycle_id
└── applied_entry_package: AppliedEntryPackage

AppliedEntryPackage
├── applied_desired_entry: DesiredEntry
└── calculated_quantity
```

The applied desired entry exists only inside `AppliedEntryPackage`; it is not
duplicated as another persisted cycle field. Phase, fill aggregates, frozen
execution context, and position-management state are not part of the current
model. Open-position facts resolved from ABI remain transient.

A strategy instance can have at most one current cycle in the active aggregate.
Cycle creation/application through entry reconciliation is implemented. Fill
processing and completed-cycle archival are not implemented.

## 5. Desired-entry lifecycle

Each successful live-entry projection returns one complete
`desired_entry: DesiredEntry | null` inside
`LiveEntryProjectedStrategyInstance`. The router itself does not mutate the
repository, choose a side, or arbitrate between plans; the closed-bar
orchestrator applies the reconciliation result afterward.

Reconciliation uses these complete-snapshot semantics:

```text
no existing cycle
-> create a cycle only after ABI acknowledges the complete package

existing acknowledged package
-> compare new and currently applied singular DesiredEntry objects

successful acknowledgement
-> replace the complete AppliedEntryPackage snapshot
```

Top-level `desired_entry = null` is data and means that no entry is currently
desired. The implemented reconciliation operation selects cancellation for an
acknowledged unfilled entry or remains a no-op when none is applied. The
top-level closed-bar orchestrator invokes that operation inside its keyed
critical section. No valid non-null cycle lacks an `AppliedEntryPackage`;
successful cancellation clears `current_trade_cycle`. An absent cycle does not
prove that ABI or the exchange
is flat.

## 6. Execution and freeze transition

The concrete ABI fill callback, execution facts, lifecycle phases, and
post-fill invariants are intentionally not modeled in I2. They depend on the
future Runtime ↔ ABI fill contract and remain an implementation gate. The
current aggregate must not be extended with speculative fill or frozen-context
fields before that contract is designed.

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
process-local non-reentrant keyed mutex per `strategy_instance_id` serializes
both top-level writer paths. Different strategy instances may proceed in
parallel.

`StrategyRuntimeOrchestrator` owns the critical section across
`get_or_create/load → ABI position lookup → Engine projection → typed branch →
live-entry reconciliation → save`. This closed-bar writer is implemented and
verified, but not yet reachable through the production bootstrap: production
outbound adapters and the composition graph that attach it to real Strategy
Engine/ABI endpoints and the closed-bar webhook are the next seam (see
[`runtime-live-entry-production-integration-plan.md`](runtime-live-entry-production-integration-plan.md)).
`AbiExecutionEventOrchestrator` will independently own the later webhook
critical section across `fresh load → event application → save`; that fill
writer is not implemented. The already implemented
`EntryReconciliationOrchestrator` does not acquire the mutex, reload state, or
save independently; it receives one projection whose provenance already embeds
the exact source aggregate.

A webhook that waits behind reconciliation must reload state after acquiring
the mutex. Holding the mutex across outbound calls is accepted for Live V1, so
every such call requires a bounded timeout. An ambiguous create/replace result
must not be retried blindly, and an ABI acknowledgement must not synchronously
depend on processing a webhook blocked by the same mutex.

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
