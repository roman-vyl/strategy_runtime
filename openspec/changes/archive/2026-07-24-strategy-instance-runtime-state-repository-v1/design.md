## Context

The utility committed-bar pipeline discovers deployment JSON files, selects
deployments matching the committed market stream, and emits one immutable
`StrategyBarProcessingUnit` per selected deployment.

`StrategyRuntimeOrchestrator.process(...)` handles one processing unit. Its first
semantic step maps the deployment into
`GetOrCreateStrategyInstanceRuntimeStateRequest` and calls
`StrategyInstanceRuntimeStateRepository.get_or_create(...)`. The returned state
then passes to open-position resolution and use-case routing.

The current repository implementation is in-memory. This capability defines
logical state ownership and in-process atomicity, not physical durability.

## Goals / Non-Goals

**Goals:**

- Define one state-repository operation: `get_or_create`.
- Use the utility-derived `strategy_instance_id` as the repository key.
- Define the exact request mapped from one `StrategyBarProcessingUnit`.
- Preserve an immutable first-registration snapshot.
- Create missing state without a current trade cycle.
- Return existing state without mutation.
- Guarantee deterministic repeated lookup and atomic in-process first creation.
- Reject a different `strategy_id` under an existing `strategy_instance_id`.

**Non-Goals:**

- No state-update or compare-and-swap operation.
- No trade-cycle creation, completion, or archival.
- No recipe creation, replacement, or freezing.
- No Open Position Resolver, Strategy Engine, or ABI behavior inside the
  repository.
- No physical database, migration, restart recovery, or cross-process locking
  contract.
- No synchronization of an existing registered snapshot from a deployment file.

## Decisions

### Use the utility-derived strategy-instance identity

The repository key is:

```text
strategy_instance_id = StrategyBarProcessingUnit.strategy_instance_id
```

The repository does not calculate this value. The deployment catalog derives it
from the canonical JSON payload:

```text
strategy_id
+ ticker
+ base_timeframe
+ raw_spec
```

`ticker`, `base_timeframe`, `strategy_id`, and `raw_spec` are separate required
fields in the same deployment JSON document. `ticker` and `base_timeframe` are
not nested inside `raw_spec`.

Any change to `strategy_id`, `ticker`, `base_timeframe`, or any value inside
`raw_spec` produces a different `strategy_instance_id`. Changing only `enabled`,
the source filename, JSON key order, formatting, or unrelated root metadata does
not change the identity.

**Rationale:** The repository receives an already established semantic identity
and does not duplicate canonicalization or hashing rules owned by the utility
catalog.

### Map one processing unit to one repository call

For each `StrategyBarProcessingUnit`,
`StrategyRuntimeOrchestrator.process(...)` calls `get_or_create(...)` exactly
once. The mapping is:

```text
strategy_instance_id <- unit.strategy_instance_id
strategy_id           <- unit.deployment.strategy_id
instrument            <- unit.deployment.instrument
base_timeframe        <- unit.deployment.base_timeframe
raw_spec              <- unit.deployment.raw_spec
source_path           <- unit.deployment.source_path
```

The committed bar is not part of this request. No utility deployment digest or
hash field crosses the repository boundary.

**Rationale:** Deployment registration data belongs to the strategy instance;
the committed bar belongs to the current processing invocation.

### Store one immutable first-registration snapshot

When the key is absent, the repository creates:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
│   ├── instrument
│   ├── base_timeframe
│   ├── raw_spec
│   └── source_path
└── current_trade_cycle = null
```

`RegisteredSpecSnapshot` validates its required strings and recursively freezes
`raw_spec`. Initial creation does not create a trade-cycle identity, entry
recipe, position-management recipe, or position facts.

**Rationale:** A complete aggregate is visible immediately after creation, while
all lifecycle transitions remain outside `get_or_create`.

### Return existing state without mutation

When state already exists under `strategy_instance_id`, the implementation:

1. rejects the request if `strategy_id` differs;
2. otherwise returns the existing aggregate object;
3. does not compare or rewrite the registered snapshot;
4. does not change the current trade cycle or either recipe.

The current conflict check therefore covers `strategy_id` only. Whether a
same-ID, same-`strategy_id` request carries different registration fields does
not change this behavior. The utility-derived `strategy_instance_id` is the
authoritative identity, so the repository intentionally does not repeat
field-by-field comparison of instrument, base timeframe, or `raw_spec`.

**Rationale:** `get_or_create` has creation and lookup semantics only; hidden
state synchronization would make the operation an update. Repeating identity
derivation or equivalence checks here would duplicate catalog ownership.

### Let the registered snapshot own defensive freezing

`GetOrCreateStrategyInstanceRuntimeStateRequest` is a short-lived transport DTO
and does not validate or freeze `raw_spec`. On first creation,
`RegisteredSpecSnapshot` validates required fields, detaches the mapping, and
recursively freezes all JSON values.

**Rationale:** Immutability is required at the long-lived ownership boundary,
not at every temporary call shape that carries the value there.

### Serialize in-process creation with `RLock`

`InMemoryStrategyInstanceRuntimeStateRepository` protects lookup and insertion
with one `RLock`. Equivalent concurrent calls for one absent key observe one
complete aggregate and return the same stored object.

**Rationale:** A single critical section provides the required in-process
atomicity without adding a persistence technology to the port.

### Return the aggregate directly

The operation returns `StrategyInstanceRuntimeState` and does not return a
separate `created` flag.

**Rationale:** Downstream behavior is based on aggregate content rather than on
whether creation happened during the current invocation.

### Keep the implemented package boundary

The capability is located at:

```text
src/strategy_runtime/runtime/state/
├── __init__.py
├── errors.py
├── models.py
└── repository.py
```

`repository.py` contains both the port and the in-memory implementation.
`src/strategy_runtime/infrastructure/runtime_state/sqlite_repository.py` is only
an empty package placeholder and is not part of this capability.

## Risks / Trade-offs

- [Process restart discards in-memory state] → This capability makes no
  durability or recovery guarantee.
- [The registered snapshot remains the first snapshot] → `get_or_create` never
  performs an implicit update.
- [Only `strategy_id` is defensively checked on an existing key] → The derived
  key remains authoritative; registration fields are not revalidated.
- [The request accepts a mutable mapping] → The long-lived
  `RegisteredSpecSnapshot` detaches and recursively freezes it at creation.

## Migration Plan

Not applicable. The capability is additive, uses no persisted schema, and
requires no data migration.

## Open Questions

None.
