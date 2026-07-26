## Context

The deployment catalog discovers strategy instances, derives
`strategy_instance_id`, and supplies immutable first-registration inputs.
Runtime state is the long-lived owner of operational settings for that
identity. Deployment discovery is not an operational update command.

The ABI entry-package client already requires a positive exact-decimal
`risk_multiplier` on every request, including requests whose
`desired_entry` is null. Later reconciliation will read the current value from
Runtime state and pass it to ABI. Strategy Engine neither receives nor
calculates this setting, and Runtime does not calculate exchange quantity.

The provisional `CurrentTradeCycle` contains fields whose invariants depend on
the not-yet-designed ABI fill contract. Live V1 remains one Runtime process with
one worker and an in-memory repository.

## Goals / Non-Goals

**Goals:**

- Make `risk_multiplier` a required, positive exact-decimal Runtime-state
  field.
- Initialize a newly registered aggregate with canonical value `"1"`.
- Keep registration discovery idempotent and unable to reset operational
  state.
- Replace provisional trade-cycle state with the minimal I2 model.
- Store one applied desired-entry acknowledgement inside
  `AppliedEntryPackage`.
- Define a production-unique Runtime-owned `trade_cycle_id` boundary.
- Add repository lookup and complete-aggregate save.
- Add process-local keyed mutual exclusion for later state writers.

**Non-Goals:**

- No multiplier in deployment JSON, `DeploymentSpecification`, `raw_spec`,
  registration requests, or identity derivation.
- No frontend, HTTP API, or application use case for changing multiplier.
- No fill phases, fill quantities, average price, fill timestamps,
  `FrozenExecutedEntryContext`, or position-management recipe.
- No interpretation of `current_trade_cycle` or package absence as proof of
  exchange position state.
- No reconciliation decision, ABI result application, fill-event application,
  HTTP handler, Engine or ABI call, routing change, or new orchestrator flow.
- No durable repository, revisions/CAS, pending commands, event
  deduplication, multi-worker support, or distributed locking.

## Decisions

### Own operational risk in Runtime state

`StrategyInstanceRuntimeState` contains:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
├── risk_multiplier
└── current_trade_cycle
```

`risk_multiplier` is a positive exact-decimal string and has no constructor
default on the aggregate. The repository explicitly supplies the internal
canonical initial value:

```text
_CANONICAL_INITIAL_RISK_MULTIPLIER = "1"
```

This is not a fallback for omitted user configuration. It is the defined
initial operational state of every newly registered strategy instance.

**Rationale:** Runtime state is the long-lived owner that later reconciliation
will read. A future explicit user command can change the stored value without
turning catalog discovery into hidden mutation.

**Alternative considered:** Put the value in deployment and copy it during
registration. That makes discovery an ambiguous risk-update source and gives
two modules ownership of one operational setting.

### Keep registration input free of operational state

`DeploymentSpecification` and
`GetOrCreateStrategyInstanceRuntimeStateRequest` contain only deployment and
first-registration data. Neither contains `risk_multiplier`.

The immutable `RegisteredSpecSnapshot` remains:

```text
instrument
base_timeframe
raw_spec
source_path
```

`strategy_instance_id` continues to derive only from:

```text
strategy_id + ticker + base_timeframe + raw_spec
```

No multiplier member in `raw_spec` is promoted to Runtime operational state.

**Rationale:** Registration establishes identity and immutable provenance.
Operational risk has a different lifecycle and needs a future explicit update
use case.

### Preserve operational state on rediscovery

`get_or_create` uses the canonical `"1"` only when the identity is absent. If
state already exists, it returns the stored aggregate without rewriting:

```text
risk_multiplier
registered_spec_snapshot
current_trade_cycle
```

A complete valid aggregate saved with another multiplier remains authoritative
on later discovery. I2 does not define how an external user requests that
change.

**Rationale:** Idempotent discovery must not be a hidden update command.

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
duplicated as a persisted cycle field. `AppliedEntryPackage` is a Runtime domain
value, not the ABI wire DTO.

`current_trade_cycle = null` means only that Runtime owns no current trade
cycle or acknowledged entry package. It does not replace ABI position lookup
and does not prove that an exchange order or position is absent.

**Rationale:** I2 needs ownership and acknowledgement storage, but the deferred
fill contract is the authority for all later execution-state fields.

### Preserve exact-decimal lexemes through shared validation

Runtime state and the existing ABI DTOs reuse non-normalizing exact-decimal
predicates from the shared decimal-text module. Validation does not convert
through `float` and does not rewrite accepted strings.

`StrategyInstanceRuntimeState.risk_multiplier` and
`AppliedEntryPackage.accepted_risk_multiplier` are positive exact-decimal text.
`AppliedEntryPackage.calculated_quantity` is finite exact-decimal text.

**Rationale:** Runtime-owned operational state and acknowledged ABI values must
retain exact decimal semantics.

### Separate injected identity creation from aggregate construction

I2 exposes a semantic `TradeCycleIdFactory` callable and a production
implementation based on UUID generation. The production implementation returns
a distinct opaque non-empty ID for each new trade cycle.

`CurrentTradeCycle` validates and stores a supplied identity; it does not
generate one in its constructor. Repository `get_or_create` does not request a
cycle identity. No `command_id`, Engine `trade_id`, or exchange-derived
identity is introduced.

### Add load and complete replacement to the repository

The repository port becomes:

```text
get_or_create(request) -> StrategyInstanceRuntimeState
get(strategy_instance_id) -> StrategyInstanceRuntimeState | null
save(state) -> StrategyInstanceRuntimeState
```

`save` replaces only an already registered aggregate and performs no partial
merge. It rejects an unknown identity and changes to persisted `strategy_id` or
`registered_spec_snapshot`. A valid `risk_multiplier` and minimal current cycle
are part of the supplied complete value and may differ from the prior
operational state.

Each in-memory operation is atomic under the repository's internal `RLock`.
A multi-call `get → save` sequence is not atomic, has no stale-write detection,
and does not acquire the application keyed mutex.

### Provide one context-managed lock per exact instance key

`StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)` uses one
non-reentrant process-local lock per exact non-empty key. An internal registry
guard atomically creates or retrieves the keyed lock, then releases the guard
before waiting on that lock.

Same-key contexts cannot overlap; different-key contexts can. Context exit
releases the keyed lock after normal completion or exception. I2 does not
inject the registry into an orchestrator.

## Risks / Trade-offs

- [A canonical initial value may later need user customization] → Defer an
  explicit user-facing update use case; do not overload deployment discovery.
- [Runtime state is in memory] → Accept restart reset to canonical `"1"` in
  Live V1 and defer durable persistence.
- [Production uniqueness is probabilistic when backed by UUID4] → Use the
  existing UUID generator and test distinct repeated calls.
- [Complete save is last-writer-wins if callers ignore keyed coordination] →
  Require later writers to share the registry; defer revisions/CAS.
- [A process-lifetime lock map grows with unique instance identities] → Accept
  bounded catalog cardinality in Live V1.

## Migration Plan

1. Keep shared exact-decimal predicates and existing ABI behavior unchanged.
2. Keep deployment and registration contracts free of `risk_multiplier`.
3. Initialize missing Runtime state with explicit canonical `"1"`.
4. Preserve saved operational state across repeated `get_or_create`.
5. Replace the provisional cycle model with minimal `CurrentTradeCycle` and
   nested `AppliedEntryPackage`.
6. Keep the production-unique trade-cycle identity boundary.
7. Keep repository get/save and keyed mutex behavior.
8. Synchronize active architecture documents and run complete verification.

There is no persisted-state migration because the repository is in memory.
Rollback requires no ABI or exchange action.

## Open Questions

None for I2. The user-facing risk update use case, physical persistence,
acknowledgement application, fill events, execution phases, frozen context, and
position management remain later design topics.
