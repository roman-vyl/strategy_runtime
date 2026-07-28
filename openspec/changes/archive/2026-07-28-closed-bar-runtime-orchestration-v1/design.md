## Context

The existing semantic Runtime path is scalar and already coordinated by
`StrategyRuntimeOrchestrator`:

```text
StrategyBarProcessingUnit
-> StrategyInstanceRuntimeStateRepository.get_or_create
-> OpenPositionResolver.resolve
-> StrategyUseCaseRouter.route
   -> Strategy Engine projection
-> LiveEntryProjectedStrategyInstance
   or OpenTradeProjectedStrategyInstance
-> return projection
```

The repository implementation, position resolver, router, projection models,
and nested `EntryReconciliationOrchestrator` already exist. The nested
operation has the exact contract:

```python
EntryReconciliationOrchestrator.execute(
    projection: LiveEntryProjectedStrategyInstance,
) -> StrategyInstanceRuntimeState
```

It extracts its source snapshot through
`projection.source.resolved_state.runtime_state`, accepts no second state
argument, and returns either a logically unchanged aggregate or a confirmed
replacement aggregate.

`StrategyInstanceKeyedMutexRegistry` also already exists. Its non-reentrant
`hold(strategy_instance_id)` context serializes one exact key, permits different
keys to overlap, and releases the lock on normal or exceptional context exit.
The in-memory repository's own `RLock` protects individual repository calls but
does not make the multi-call application workflow atomic.

This change extends `StrategyRuntimeOrchestrator` in place from its current
projection stopping point. It owns the complete closed-bar critical section and
the decision to persist a logical transition. No new top-level orchestrator is
introduced.

The design is constrained to the accepted Live V1 deployment boundary: one
Runtime process and one worker, no cross-process coordination guarantee, and no
repository CAS or durable pending-action protocol.

## Goals / Non-Goals

**Goals:**

- Acquire the shared keyed mutex before the first state load and hold it through
  every synchronous application step and optional save.
- Preserve the existing repository → resolver → router/Engine projection
  sequence without moving domain logic into the top-level orchestrator.
- Dispatch the two existing projection variants by typed branch.
- Invoke the existing live-entry nested operation once with the exact
  projection and no second state argument.
- Persist a complete replacement aggregate once only when domain value changed.
- Return the final `StrategyInstanceRuntimeState` from `process(...)`.
- Fail explicitly for the deferred open-trade branch and fail closed for an
  unknown projection type.
- Propagate semantic errors and always release the keyed mutex without retry,
  fallback, error-to-`NoOp` conversion, or partial replacement save.
- Preserve `dispatch(...)` and `CommittedBarOrchestrator` error-ownership
  boundaries.

**Non-Goals:**

- No new top-level closed-bar, projection, or persistence orchestrator.
- No changes to position-resolution, use-case routing, Engine mapping,
  reconciliation decision, command construction, or confirmation-application
  rules.
- No open-trade application operation or position-management state transition.
- No production `StrategyCycleHandoffBoundary` attachment and no change to
  `bootstrap/application.py`.
- No concrete Strategy Engine HTTP, ABI open-position HTTP, or
  entry-reconciliation execution adapter.
- No Runtime URL, timeout, Docker, or cross-service integration configuration.
- No ABI execution-webhook workflow or entry/fill cross-flow tests.
- This change does not alter the accepted Live V1 persistence, recovery, or
  deployment constraints.
- No new result DTO merely to carry a `changed` boolean.
- No canonical spec or system-plan edits while this change is under review.

## Decisions

### Extend the existing orchestrator and inject existing application boundaries

`StrategyRuntimeOrchestrator` remains the single top-level coordinator for one
closed-bar processing unit. Its construction gains the already implemented
coordination and reconciliation dependencies:

```text
state_repository
open_position_resolver
use_case_router
keyed_mutex_registry
entry_reconciliation_orchestrator
```

The constructor uses the existing concrete application protocols and classes;
it does not define replacement router, resolver, repository, mutex, or
reconciliation abstractions.

**Rationale:** State lifetime and serialization belong at the component that
already sequences the complete semantic call. Introducing another coordinator
would split ownership and duplicate the current orchestration boundary.

**Alternative considered:** Wrap `StrategyRuntimeOrchestrator` in a new
closed-bar orchestrator. That would create two competing top-level workflows
and make it unclear which component owns load/save and exception-safe lock
release.

### Own one keyed critical section from before load through terminal behavior

`process(...)` enters:

```text
keyed_mutex_registry.hold(unit.strategy_instance_id)
```

before calling `state_repository.get_or_create(...)`. Everything after
acquisition remains in that context:

```text
acquire keyed mutex
-> get_or_create state
-> resolve authoritative ABI position facts
-> route and obtain Strategy Engine projection
-> supported typed branch
-> optional live-entry reconciliation
-> optional save
-> return final aggregate or raise
-> release keyed mutex
```

The context boundary, rather than per-stage cleanup code, owns release. Normal
return and every exception unwind the same context. This includes errors from
state `get_or_create`, position resolution, router or Engine projection,
reconciliation, unsupported or unknown projection branches, and repository
save.

The nested `EntryReconciliationOrchestrator` does not reacquire the
non-reentrant mutex. The repository lock is not treated as a substitute for
this application critical section.

**Rationale:** Loading after lock acquisition prevents two same-instance
writers from deriving work from stale snapshots. Holding the lock through save
makes one same-instance invocation logically indivisible within the accepted
single-process boundary.

**Alternatives considered:** Locking only around save allows overlapping
lookups and projections against stale state. Acquiring inside the nested
operation omits load/resolution/projection and would deadlock if both layers
used the same non-reentrant mutex.

### Preserve the projection pipeline as delegated application calls

Inside the critical section, the existing order remains:

```text
state_repository.get_or_create(request)
-> open_position_resolver.resolve(state)
-> use_case_router.route(PositionResolvedStrategyInstance(unit, resolved))
```

`StrategyUseCaseRouter.route(...)` continues to own route selection and the
Strategy Engine call. `StrategyRuntimeOrchestrator` neither reads position
facts to choose an Engine method nor constructs projection objects. It receives
the typed projection produced by the router and coordinates only the next
application step.

**Rationale:** The existing components already contain the authoritative
identity checks, position rules, Engine request mapping, and synchronous source
binding.

**Alternative considered:** Calling Engine ports or reproducing position
selection in the top-level orchestrator would duplicate canonical router and
resolver behavior.

### Use a typed branch after projection

The post-Engine branch recognizes the two existing projection variants:

```text
LiveEntryProjectedStrategyInstance
-> live-entry branch

OpenTradeProjectedStrategyInstance
-> unsupported branch

any other result
-> fail closed
```

It does not dispatch by a string discriminator, dictionary shape, class name,
or presence of attributes. The branch is typed by the two supported projection
variants; any other result is treated as a violated router contract.

For a live-entry projection, the orchestrator calls exactly:

```python
entry_reconciliation_orchestrator.execute(projection)
```

once. It passes the exact projection returned by the router and never supplies
the loaded state as a second argument. The nested operation remains responsible
for extracting:

```python
projection.source.resolved_state.runtime_state
```

For an open-trade projection, `process(...)` raises the new typed
`OpenTradeProjectionUnsupportedError`. It does not call live-entry
reconciliation, save state, return the projection, or permit `dispatch(...)` to
report success.

Any other result raises a distinct fail-closed
`UnknownStrategyProjectionError`. That path has no reconciliation, save,
fallback, or successful result.

**Rationale:** The union is closed in the type model, but runtime validation is
still required at an application boundary. Separate error types distinguish a
known deferred use case from a violated router contract.

**Alternatives considered:** Attribute probing and string discriminators weaken
the existing typed boundary. Treating unknown values as open-trade or `NoOp`
could acknowledge unsupported work as successful.

### Detect a logical transition with aggregate value equality

For the live-entry branch:

```text
source_state = projection.source.resolved_state.runtime_state
resulting_state = entry_reconciliation_orchestrator.execute(projection)
```

The orchestrator compares the immutable aggregates by their existing dataclass
value equality:

```python
resulting_state != source_state
```

It must not use:

```python
resulting_state is not source_state
```

If values are equal, the operation is a logical `NoOp`: `save(...)` is not
called even if the nested operation returned a different Python object. If
values differ, the orchestrator passes the complete replacement aggregate to
`state_repository.save(resulting_state)` exactly once and returns the exact
`StrategyInstanceRuntimeState` that `save(...)` returns. The repository
contract guarantees that `save(...)` returns the persisted aggregate. The
repository operation remains responsible for atomically accepting or rejecting
the complete replacement; the top-level orchestrator performs no partial field
merge.

```text
if resulting_state == source_state:
    return resulting_state

saved_state = state_repository.save(resulting_state)
return saved_state
```

No `changed` result DTO is added because the existing immutable aggregate
equality expresses the required distinction.

**Rationale:** Persistence follows a domain-value transition, not an
implementation-specific allocation choice. This preserves the nested
operation's explicit freedom to return a value-equivalent object for `NoOp`.

**Alternatives considered:** Python identity creates false saves for copied but
equal aggregates. Always saving obscures `NoOp` and violates required save
cardinality. Adding a wrapper DTO duplicates information already represented by
aggregate equality.

### Return aggregate state and keep dispatch as a thin adapter

The public semantic operation becomes:

```python
StrategyRuntimeOrchestrator.process(
    unit: StrategyBarProcessingUnit[DeploymentSpecification],
) -> StrategyInstanceRuntimeState
```

It no longer returns `StrategyUseCaseProjectedInstance`. A successful
live-entry call returns the logically unchanged or replacement aggregate
produced by reconciliation. A projection is an intermediate value only.

`dispatch(...)` remains:

```text
process succeeds
-> StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)

process raises
-> same exception propagates
```

It does not catch semantic exceptions or create a failed outcome.
`CommittedBarOrchestrator` remains the existing owner that catches a dispatcher
exception and creates `strategy_cycle_dispatch_failed`.

**Rationale:** The semantic method's terminal application result is state,
while the utility dispatch contract still needs only success or propagated
failure.

**Alternative considered:** Returning the projection after reconciliation
would report an obsolete stopping point and hide the actual state outcome.
Creating failed outcomes in `dispatch(...)` would duplicate and bypass the
committed-bar failure-isolation policy.

### Propagate errors without recovery or partial application

The workflow catches no dependency exception for translation, retry, fallback,
or conversion into `NoOp`. Resolver, Engine, reconciliation, and repository
errors propagate as raised. The two branch-validation errors are raised
directly by this orchestrator.

Before save, all state models are immutable and repository replacement has not
occurred. On any pre-save failure, `save(...)` has zero calls. A save failure
propagates after exactly one attempted call; the repository's existing atomic
save contract prevents partial merge, and the orchestrator performs no retry.
This change does not alter the accepted Live V1 persistence, recovery, or
deployment constraints.

**Rationale:** This change does not alter the accepted Live V1 persistence,
recovery, or deployment constraints.

**Alternative considered:** Retry or fallback is unsafe for ambiguous external
entry-package outcomes and would broaden this change into a reliability
protocol.

## Risks / Trade-offs

- [The mutex is held across ABI lookup, Engine projection, reconciliation
  execution, and save] → This is the accepted Live V1 consistency trade-off;
  production adapters and bounded timeout configuration are a separate
  integration seam.
- [One slow same-instance call delays later work for that instance] → Different
  instance keys remain independent, and tests prove they can overlap.
- [Process-local locks do not coordinate multiple workers or replicas] → This
  change does not alter the accepted Live V1 persistence, recovery, or
  deployment constraints.
- [Changing `process(...)` return type breaks projection-returning callers and
  tests] → Update only focused application callers/tests in implementation;
  `dispatch(...)` retains its utility outcome contract, and production handoff
  wiring is not yet active.
- [Typed branch rejects unsupported projection variants] → This is
  deliberate fail-closed behavior; each future projection branch requires an
  explicit design and orchestrator update.
