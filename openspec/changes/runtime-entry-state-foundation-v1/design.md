## Context

The deployment catalog currently validates `enabled`, ticker, timeframe,
strategy identity, and opaque `raw_spec`, then derives
`strategy_instance_id`. Runtime state is created from that deployment but does
not yet carry user risk configuration. Its provisional `CurrentTradeCycle`
also contains fields that assume later execution lifecycle decisions.

The ABI entry-package client is implemented and requires a positive
exact-decimal `risk_multiplier` on every request. The later reconciliation
change will need a Runtime-owned cycle identity and somewhere to store one
successful applied-package acknowledgement. The ABI fill-event contract has not
yet been designed, so phases, fills, frozen context, and position-management
state cannot be part of I2.

Live V1 remains one Runtime process with one worker and an in-memory
repository. I2 establishes only the deployment-to-state configuration path,
minimal current-cycle ownership, repository mutation boundary, and
process-local coordination primitive.

## Goals / Non-Goals

**Goals:**

- Require user-authored top-level deployment `risk_multiplier` with no default.
- Carry that exact value into newly registered strategy-instance state without
  changing instance identity derivation.
- Replace the provisional trade-cycle state with the minimal I2 model.
- Store the complete applied desired entry inside one `AppliedEntryPackage`.
- Define a production-unique Runtime-owned `trade_cycle_id` boundary.
- Add repository lookup and complete-aggregate save.
- Add process-local keyed mutual exclusion for later state writers.

**Non-Goals:**

- No default, fallback, or derivation for `risk_multiplier`.
- No fill phases, fill quantities, average price, fill timestamps,
  `FrozenExecutedEntryContext`, or position-management recipe.
- No interpretation of `current_trade_cycle` or package absence as proof of
  exchange position state.
- No reconciliation decision, ABI result application, fill-event application,
  HTTP handler, Engine or ABI call, routing change, or orchestrator wiring.
- No risk-multiplier update use case.
- No durable repository, revisions/CAS, pending commands, event
  deduplication, multi-worker support, or distributed locking.

## Decisions

### Make `risk_multiplier` required deployment configuration

Every deployment document contains:

```text
risk_multiplier: positive exact-decimal string
```

The field is top-level beside `enabled`, `ticker`, `base_timeframe`,
`strategy_id`, and `raw_spec`. Missing, null, numeric, boolean, zero, negative,
or invalid exact-decimal values make that deployment file invalid. A
`risk_multiplier` member inside `raw_spec` does not satisfy the required
top-level field.

The catalog preserves the accepted string lexeme in
`DeploymentSpecification`. There is no default at the catalog, repository
request, or state-model boundary.

**Rationale:** Risk sizing is user-owned operational deployment configuration,
not Engine strategy calculation state. Requiring it at discovery makes omitted
configuration fail closed before any Runtime or ABI activity.

**Alternative considered:** Default to `"1"` or read the field from
`raw_spec`. Both hide missing user configuration and mix operational risk with
Engine-owned strategy semantics.

### Exclude risk configuration from strategy-instance identity

`strategy_instance_id` continues to derive only from:

```text
strategy_id + ticker + base_timeframe + raw_spec
```

`risk_multiplier`, like `enabled`, is preserved deployment-local data but does
not change the derived identity. Two files differing only by risk multiplier
therefore resolve to the same identity and are handled by the existing
duplicate-identity fail-closed rule.

**Rationale:** Updating operational risk must not create another long-lived
strategy deployment identity.

**Alternative considered:** Include risk in the identity basis. That would
fork Runtime state and trade history whenever a user changes sizing.

### Carry the user value into initial Runtime state

`GetOrCreateStrategyInstanceRuntimeStateRequest` copies the exact deployment
`risk_multiplier`. Missing state is created with that value:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
├── risk_multiplier
└── current_trade_cycle
```

The field remains outside `RegisteredSpecSnapshot`, whose existing purpose is
to preserve instrument, base timeframe, `raw_spec`, and source path. Repeated
`get_or_create` for an existing identity returns the stored aggregate and does
not treat deployment rediscovery as a risk-update operation. I2 adds no
separate update use case.

**Rationale:** Initial state must receive the user choice, while repository
registration remains idempotent and cannot silently mutate operational state.

**Alternative considered:** Reapply the current deployment value on every
bar. That would turn read-oriented discovery into an implicit state mutation
and bypass later reconciliation policy.

### Keep the I2 current-cycle aggregate deliberately minimal

I2 replaces the provisional model with:

```text
CurrentTradeCycle
├── trade_cycle_id
└── applied_entry_package: AppliedEntryPackage | null
```

and:

```text
AppliedEntryPackage
├── applied_desired_entry
├── accepted_risk_multiplier
└── calculated_quantity
```

The applied desired entry is nested only inside the package and is not
duplicated as a cycle field. `AppliedEntryPackage` is a Runtime domain value,
not the ABI wire DTO; later application logic will perform the explicit
mapping.

`current_trade_cycle = null` means only that Runtime owns no current cycle.
`applied_entry_package = null` means only that the Runtime cycle does not
currently record an applied package. Neither state proves that an exchange
position or order is absent.

**Rationale:** I2 needs ownership and acknowledgement storage, but the deferred
fill contract is the authority for all later execution-state fields.

**Alternative considered:** Add phases, frozen context, fill aggregates, or
management state now. Their invariants depend on the still-undesigned ABI fill
event and would prematurely constrain I5.

### Preserve exact-decimal lexemes through shared validation

Deployment and state models reuse non-normalizing exact-decimal predicates in
the shared decimal-text module. Validation does not convert through `float`
and does not rewrite accepted strings. The existing ABI DTOs use the same
shared predicates so the catalog, state, and wire boundary agree on decimal
grammar.

`accepted_risk_multiplier` is positive exact-decimal text.
`calculated_quantity` follows the already approved ABI client contract and is
finite exact-decimal text.

**Rationale:** The user-authored multiplier and acknowledged values must reach
later ABI requests without precision loss or hidden lexical normalization.

**Alternative considered:** Import validation from the ABI DTO module into
deployment and state. That reverses dependency direction and couples core
models to one transport adapter.

### Separate injected identity creation from aggregate construction

I2 exposes a semantic `TradeCycleIdFactory` callable and a production
implementation based on UUID generation. The production implementation must
return a distinct opaque non-empty ID for every new trade cycle. Tests may
inject deterministic factories, but production code cannot reuse an identity
for two cycles.

`CurrentTradeCycle` validates and stores a supplied identity; it does not
generate one in its constructor. Repository `get_or_create` does not request a
cycle identity. No `command_id`, Engine `trade_id`, or exchange-derived
identity is introduced.

**Rationale:** Later reconciliation must control when identity is reserved and
must bind the same value to Runtime state and the ABI request.

**Alternative considered:** Generate an ID automatically in the aggregate or
promise only a non-empty string. The former hides sequencing; the latter does
not protect cycle ownership from identity reuse.

### Add load and complete replacement to the repository

The repository port becomes:

```text
get_or_create(request) -> StrategyInstanceRuntimeState
get(strategy_instance_id) -> StrategyInstanceRuntimeState | null
save(state) -> StrategyInstanceRuntimeState
```

`save` replaces only an already registered aggregate and performs no partial
merge. It rejects an unknown identity and rejects changes to the persisted
`strategy_id` or `registered_spec_snapshot`. A valid `risk_multiplier` and
minimal current cycle are part of the supplied complete value.

Each in-memory operation is atomic under the repository's internal `RLock`.
A multi-call `get → save` sequence is not atomic, has no stale-write
detection, and does not acquire the application keyed mutex.

**Rationale:** Later writers need explicit load and whole-aggregate
replacement, while Live V1 deliberately defers a stronger persistence
protocol.

**Alternative considered:** Partial patch methods or repository transactions.
Partial updates weaken aggregate invariants; a transaction/CAS protocol is
outside the approved single-process Live V1 scope.

### Provide one context-managed lock per exact instance key

`StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)` uses one
non-reentrant process-local lock per exact non-empty key. An internal registry
guard atomically creates or retrieves the keyed lock, then releases the guard
before waiting on that lock.

Same-key contexts cannot overlap; different-key contexts can. Context exit
releases the keyed lock after normal completion or exception. The registry
keeps created locks for its process lifetime.

I2 does not inject the registry into an orchestrator. Later state writers must
share one registry instance through production composition.

**Rationale:** The repository lock protects one dictionary operation only.
The keyed boundary is required later to serialize a complete application-level
critical section without prematurely introducing distributed coordination.

**Alternative considered:** Reuse the repository `RLock` or add a distributed
lock. The former cannot cover future work outside one repository call; the
latter exceeds the Live V1 deployment model.

## Risks / Trade-offs

- [Existing deployment files omit a now-required field] → Update all fixtures
  and example deployments in the same implementation; missing configuration
  remains a fail-closed catalog diagnostic.
- [Changing deployment risk does not change identity or automatically update
  existing state] → Preserve identity and initial registration semantics; add a
  deliberate risk-update use case only when its reconciliation behavior is
  designed.
- [Production uniqueness is probabilistic when backed by UUID4] → Use the
  existing cryptographically strong UUID generator and test that repeated
  production calls do not reuse values; never accept a user- or exchange-
  supplied cycle ID.
- [Complete save is last-writer-wins if callers ignore keyed coordination] →
  Keep the limitation explicit and require later state writers to share the
  registry; add revisions/CAS only at the deferred durability gate.
- [A process-lifetime lock map grows with unique deployment identities] →
  Accept bounded catalog cardinality in Live V1 and revisit eviction only if
  identities become dynamically unbounded.

## Migration Plan

1. Move or expose non-normalizing decimal predicates in the shared module and
   keep ABI client behavior unchanged.
2. Add required `risk_multiplier` parsing and modeling to deployment catalog
   and migrate all deployment fixtures.
3. Carry multiplier through the get-or-create request into initial Runtime
   state with no default.
4. Replace the provisional cycle model with minimal `CurrentTradeCycle` and
   nested `AppliedEntryPackage`.
5. Add the production-unique trade-cycle identity factory boundary.
6. Extend and test repository get/save.
7. Add and concurrency-test the keyed mutex registry.
8. Run the complete verification suite and confirm no fill, routing,
   orchestration, Engine, or ABI behavior entered the diff.

There is no persisted-state migration because the repository is in memory and
the active production contour does not create current cycles. Rollback restores
the prior deployment/model contracts and requires no ABI or exchange action.

## Open Questions

None for I2. Risk hot updates, acknowledgement application, fill events,
execution phases, frozen context, and position management remain later design
topics.
