# Runtime durable state repository — deferred backlog plan

Status: **DEFERRED / BACKLOG**

This document records the proposed design for durable persistence of
`StrategyInstanceRuntimeState` in Strategy Runtime.

The work is intentionally deferred until after the first successful
cross-service smoke path:

```text
MDS
→ Strategy Runtime
→ Strategy Engine
→ Runtime reconciliation
→ ABI entry-package API
→ executor bot
→ Bybit demo/testnet
```

Durable persistence is a product-reliability improvement. It is not required to
prove that the current end-to-end command pipeline works across all service
boundaries.

---

## 1. Current state

Runtime currently uses:

```text
InMemoryStrategyInstanceRuntimeStateRepository
```

Conceptually, it stores state in:

```python
dict[str, StrategyInstanceRuntimeState]
```

The repository port already exposes the required application-facing operations:

```text
get_or_create(...)
get(strategy_instance_id)
save(state)
```

The current aggregate is:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
├── risk_multiplier
└── current_trade_cycle
    ├── trade_cycle_id
    └── applied_entry_package
        ├── applied_desired_entry
        └── calculated_quantity
```

The production composition created in I4d owns exactly one shared state
repository instance and one shared keyed-mutex registry for the lifetime of the
Runtime application.

The limitation is that the repository is process memory only. After Runtime
restarts, the process loses every stored aggregate.

The existing SQLite module is only a placeholder:

```text
src/strategy_runtime/infrastructure/runtime_state/sqlite_repository.py
```

---

## 2. Problem this future change will solve

Today the following situation is possible:

```text
ABI has a live entry order
Runtime restarts
Runtime loses current_trade_cycle
Runtime sees an empty in-memory aggregate
```

That becomes especially dangerous once I5 introduces fill events:

```text
ABI receives a fill
ABI durably stores an outbox event
Runtime restarts and forgets the trade cycle
ABI redelivers the event
Runtime no longer has the state needed to apply it safely
```

A durable repository will allow Runtime to restart and continue the same
strategy instance and the same trade cycle.

---

## 3. Architectural approach

The orchestration, reconciliation, state models, and repository port should not
be redesigned.

Only the repository implementation changes:

```text
Current:

StrategyRuntimeOrchestrator
→ InMemoryStrategyInstanceRuntimeStateRepository
→ Python process memory
```

```text
Target:

StrategyRuntimeOrchestrator
→ SqliteStrategyInstanceRuntimeStateRepository
→ runtime_state.sqlite
```

The rest of Runtime should continue using the same repository interface:

```text
get_or_create(...)
get(...)
save(...)
```

The orchestrators must not know whether the implementation is in-memory or
SQLite-backed.

---

## 4. Proposed OpenSpec change

Suggested change name:

```text
runtime-durable-strategy-instance-state-v1
```

The change should be scoped to durable persistence of the existing Runtime
aggregate.

It should not include:

- ABI fill webhook implementation;
- Bybit WebSocket ingestion;
- ABI execution ledger or outbox;
- webhook authentication;
- open-trade orchestration;
- durable MDS webhook inbox;
- multi-worker coordination;
- distributed locking;
- a broker or worker framework.

---

## 5. Proposed persisted model

A simple full-snapshot schema is preferred for V1.

```sql
CREATE TABLE strategy_instance_runtime_state (
    strategy_instance_id TEXT PRIMARY KEY,
    strategy_id          TEXT NOT NULL,
    schema_version       INTEGER NOT NULL,
    state_json           TEXT NOT NULL,
    updated_at_ms        INTEGER NOT NULL
);
```

The complete aggregate is stored in `state_json`.

Example:

```json
{
  "strategy_instance_id": "ema_pullback:instance-1",
  "strategy_id": "ema_pullback",
  "registered_spec_snapshot": {
    "instrument": "BTCUSDT.P",
    "base_timeframe": "5m",
    "raw_spec": {},
    "source_path": "deployments/ema-pullback.json"
  },
  "risk_multiplier": "1",
  "current_trade_cycle": {
    "trade_cycle_id": "trade-cycle-1",
    "applied_entry_package": {
      "applied_desired_entry": {
        "side": "long",
        "source_plan_bar_open_time_ms": 0,
        "planned_entry_price": "100",
        "initial_stop_price": "95",
        "initial_take_price": "110",
        "locked_exit_profile": "default"
      },
      "calculated_quantity": "0.001"
    }
  }
}
```

### Why a full aggregate snapshot is appropriate

Runtime reads and saves the aggregate as one unit. It does not currently need
arbitrary SQL queries over individual internal fields.

A full versioned snapshot provides:

- atomic aggregate replacement;
- fewer opportunities for cross-table inconsistency;
- exact-decimal values preserved as strings;
- straightforward serializer/deserializer logic;
- easier extension when I5 adds fill lifecycle fields;
- simpler migration between aggregate schema versions.

---

## 6. Schema versioning

`schema_version` should exist from the first durable version.

The current persisted model can be version 1.

I5 is expected to add fields such as:

```text
phase
cumulative_filled_quantity
remaining_quantity
average_entry_price
FrozenExecutedEntryContext
first_fill_at
last_fill_at
```

When that happens, Runtime should migrate a version-1 snapshot into a
version-2 aggregate explicitly.

Unknown future schema versions must fail closed. Runtime must not silently
interpret them as the current model.

---

## 7. Explicit serialization

Persistence must use an explicit codec for
`StrategyInstanceRuntimeState`.

Do not use:

- `pickle`;
- implicit dataclass serialization;
- binary floating-point conversion for prices or quantities;
- permissive reconstruction that ignores unknown or missing fields.

The codec should:

1. Serialize every domain field explicitly.
2. Preserve exact-decimal strings exactly.
3. Restore immutable/frozen domain structures.
4. Validate identity and domain invariants during decoding.
5. Reject malformed or unsupported snapshots.
6. Attach a clear typed persistence/codec error.

---

## 8. `get_or_create` behavior

The future SQLite implementation should make `get_or_create` transactional.

Conceptually:

```text
BEGIN IMMEDIATE

SELECT state
FROM strategy_instance_runtime_state
WHERE strategy_instance_id = ?

if row exists:
    decode and validate the aggregate
    verify immutable identity
    return it
else:
    construct initial aggregate
    risk_multiplier = "1"
    current_trade_cycle = null
    INSERT full snapshot
    return it

COMMIT
```

Required guarantees:

- concurrent equivalent creation produces one aggregate;
- the authoritative `strategy_instance_id` remains the primary key;
- a conflicting `strategy_id` fails with the existing identity error;
- rediscovery does not reset `risk_multiplier`;
- rediscovery does not overwrite the registered spec snapshot;
- an existing trade cycle survives deployment rediscovery.

---

## 9. `get` behavior

`get(strategy_instance_id)` should:

1. Validate the identifier.
2. Read the one persisted row.
3. Return `None` when the row does not exist.
4. Decode and validate the full aggregate.
5. Fail closed if the snapshot is corrupt or has an unsupported schema version.

It must not fabricate an empty aggregate when a stored row exists but cannot be
decoded.

---

## 10. `save` behavior

`save(state)` should replace the full aggregate atomically.

Conceptually:

```text
BEGIN IMMEDIATE

SELECT current row

if missing:
    fail StrategyInstanceStateNotFound

validate:
    strategy_instance_id unchanged
    strategy_id unchanged
    registered_spec_snapshot unchanged

UPDATE:
    schema_version
    state_json
    updated_at_ms

COMMIT
```

Required guarantees:

- failure before commit leaves the previous complete aggregate;
- success after commit exposes the new complete aggregate;
- no partially updated aggregate is observable;
- immutable identity/registration constraints remain enforced;
- exact-decimal values remain strings;
- save returns the saved aggregate, matching the existing repository port.

---

## 11. Configuration

Suggested configuration field:

```text
RUNTIME_STATE_DB_PATH
```

Example:

```text
RUNTIME_STATE_DB_PATH=/var/lib/strategy-runtime/runtime_state.sqlite
```

Startup preparation should:

- verify that the parent directory is usable;
- create/open the database;
- apply the supported schema initialization or migration;
- fail Runtime readiness if the database cannot be opened or validated.

No ready production application should be returned with a partially initialized
state repository.

---

## 12. Production composition change

After the SQLite repository is implemented, `build_application()` should
replace:

```python
InMemoryStrategyInstanceRuntimeStateRepository()
```

with:

```python
SqliteStrategyInstanceRuntimeStateRepository(...)
```

The composition root should still create exactly one repository instance.

That same object must be shared by:

```text
StrategyRuntimeOrchestrator
AbiExecutionEventOrchestrator  # future I5 writer
```

The existing shared `StrategyInstanceKeyedMutexRegistry` must also remain common
to both writers.

The SQLite connection/resource lifecycle should be owned by the application
composition root and closed during application shutdown.

---

## 13. Concurrency model

The existing keyed mutex remains the application-level serialization owner for
one `strategy_instance_id`.

SQLite transactions provide storage atomicity, but they do not replace the
domain critical section.

The intended flow remains:

```text
acquire shared keyed mutex
→ load fresh aggregate from SQLite
→ perform state-dependent operation
→ save replacement aggregate transactionally
→ release keyed mutex
```

For Live V1, this remains a single-process, single-worker design unless a later
change explicitly introduces cross-process coordination or optimistic
concurrency.

---

## 14. Tests

### Repository parity tests

Run the same behavioral contract against both:

```text
InMemoryStrategyInstanceRuntimeStateRepository
SqliteStrategyInstanceRuntimeStateRepository
```

Cover:

- first `get_or_create`;
- repeated equivalent `get_or_create`;
- identity conflict;
- registration conflict;
- `get` missing/existing;
- `save` missing state;
- successful replacement save;
- risk multiplier persistence;
- current trade cycle persistence.

### Restart tests

The central acceptance test:

```text
create repository A
→ create aggregate
→ save CurrentTradeCycle
→ close repository A
→ create repository B using the same database file
→ load the same aggregate
→ assert the same trade_cycle_id, applied package, quantity, spec snapshot,
  and risk_multiplier
```

### Atomicity tests

Cover:

- interrupted/failed transaction does not expose partial state;
- failed save preserves the previous aggregate;
- malformed persisted JSON fails closed;
- unknown schema version fails closed;
- exact-decimal strings survive round-trip unchanged.

### Concurrency tests

Cover:

- concurrent equivalent `get_or_create`;
- concurrent access to different strategy instances;
- one shared repository instance used across multiple cycles;
- repository operations remain correct under the existing keyed mutex.

### Production composition tests

Cover:

- `build_application()` constructs the SQLite implementation;
- exactly one repository instance is exposed in application state;
- startup fails closed for an invalid database path or corrupt database;
- shutdown closes the repository once;
- production vertical E2E still reaches Engine and ABI;
- after application restart, a previously acknowledged
  `CurrentTradeCycle` is loaded instead of recreated as empty.

---

## 15. Result of the future change

### Runtime remembers the trade cycle after restart

Before:

```text
ABI has a live order
Runtime restarts
current_trade_cycle becomes null
```

After:

```text
ABI has a live order
Runtime restarts
Runtime reloads the same trade_cycle_id
Runtime retains the acknowledged applied package and quantity
```

### I5 webhook can become restart-safe

Example:

```text
Runtime receives a partial-fill webhook
→ applies the new cumulative aggregate
→ commits SQLite state
→ crashes before returning HTTP 2xx
```

ABI redelivers the event because delivery is at-least-once.

After restart:

```text
incoming cumulative == stored cumulative
→ idempotent 2xx no-op
```

Runtime does not double-apply the fill.

### Frozen entry context survives restart

The first execution in I5 will freeze the executed entry context. Durable state
ensures that this context survives:

- Runtime restart;
- webhook retry;
- later closed-bar cycles;
- transition to the future open-trade branch.

### ABI outbox gains a durable receiver

The complete restart-safe relationship becomes:

```text
ABI outbox persists pending delivery
Runtime SQLite persists the applied aggregate
ABI retries after either service restarts
Runtime resumes from the stored state
```

---

## 16. What this change does not solve

A durable aggregate repository alone does not provide:

- durable storage of accepted-but-not-yet-processed MDS webhooks;
- recovery of a background cycle lost after Runtime already returned
  `200 accepted`;
- Bybit private WebSocket ingestion;
- ABI execution ledger;
- ABI webhook outbox;
- webhook authentication;
- Runtime fill-event HTTP endpoint;
- fill aggregation or state transitions;
- distributed locking;
- safe multi-process/multi-worker writes;
- open-trade management.

A separate durable inbox/queue would be needed to replay an MDS webhook that
Runtime acknowledged but never processed. That mechanism is deliberately not
part of this backlog item.

---

## 17. Timing and priority

This change must not be implemented before the first cross-service smoke.

Current priority:

```text
1. Close ABI production ticker → Bybit symbol resolution.
2. Wire the resolver into entry-package execution.
3. Start MDS, Strategy Runtime, Strategy Engine, and ABI together.
4. Prepare a real deployment/spec.
5. Send a closed-bar event from MDS.
6. Trace the command through Runtime and Engine.
7. Observe create/amend/cancel behavior in ABI and Bybit demo/testnet.
8. Fix real integration mismatches found by that smoke.
9. Return to durable Runtime state persistence.
```

During the first smoke:

- Runtime must not be restarted in the middle of the scenario;
- loss of in-memory state on restart is an accepted test limitation;
- no claim of restart-safe production operation should be made.

---

## 18. Backlog decision

```text
DECISION

Durable Strategy Runtime state persistence is approved as a future
product-reliability change.

It is not a prerequisite for the first full pipeline smoke.

Do not implement it until the current MDS → Runtime → Engine → ABI → Bybit
pipeline has been started and exercised end to end.

After the smoke, implement it as a separate OpenSpec change:
runtime-durable-strategy-instance-state-v1.
```
