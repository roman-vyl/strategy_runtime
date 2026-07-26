## Context

The current semantic Runtime path produces a typed
`LiveEntryProjectedStrategyInstance`. Its provenance chain already retains the
immutable state snapshot on which position resolution and projection were
based:

```text
projection
└── source
    └── resolved_state
        └── runtime_state: StrategyInstanceRuntimeState
```

The existing top-level workflow loads that state once, passes it through
`OpenPositionResolver`, and preserves it through `StrategyUseCaseRouter` into
the projection. The nested operation therefore consumes the completed
projection result rather than asking its caller to unpack and pass the same
state again.

The pure `runtime/entry_reconciliation` package already decides
`NoOp | Apply | Replace | Cancel`, builds the transport-free
`EntryReconciliationCommand`, and applies a matching
`SuccessfulEntryConfirmation`.

Those pure pieces intentionally do not decide when to reserve a
`trade_cycle_id`, invoke an external boundary, or order the complete
application operation. The new orchestrator fills only that composition seam.
A later change will call it from inside the critical section owned by
`StrategyRuntimeOrchestrator`; the nested operation itself does not own the
critical section or persistence.

## Goals / Non-Goals

**Goals:**

- Define one exact application operation from
  `LiveEntryProjectedStrategyInstance` to logically unchanged or replacement
  `StrategyInstanceRuntimeState`.
- Extract one exact `source_state` from the projection and use that same
  snapshot for reconciliation, command construction, execution, and
  confirmation application.
- Reuse the existing pure decision, command-builder, and
  successful-confirmation applier contracts without duplicating their logic.
- Reserve a new trade-cycle identity exactly once and only for `Apply`.
- Execute each command-bearing decision exactly once through a narrow injected
  port that receives both the command and its exact source-state snapshot.
- Keep the pair `(command, source_state)` sufficient for a future adapter to
  target the canonical ABI entry-package client contract without defining that
  adapter in this capability.
- Make successful confirmation the only boundary after which replacement state
  can be constructed.
- Preserve the source aggregate and propagate every execution or invariant
  failure without retry, fallback, or intermediate application state.
- Keep the dependency direction from the application layer toward the existing
  pure layer.

**Non-Goals:**

- No extension of `StrategyRuntimeOrchestrator` or its closed-bar control flow.
- No mutex acquisition, repository load/create/save, transaction, revision, or
  CAS behavior.
- No production composition, handoff wiring, processing-journal behavior, or
  error-reporting policy.
- No concrete external adapter, request or response adaptation, transport
  model, codec, or transport-error translation.
- No Engine call, open-position lookup, open-trade behavior, fill webhook, or
  execution-event lifecycle.
- No retry, fallback command, pending action, suppression flag, recovery state,
  or idempotency mechanism.
- No changes to pure reconciliation models or canonical specifications.

## Decisions

### Use one nested application operation with an exact state contract

The future application package is:

```text
strategy_runtime.runtime.entry_reconciliation_orchestrator
├── orchestrator.py
└── ports.py
```

Its public operation is conceptually:

```text
EntryReconciliationOrchestrator.execute(
    projection: LiveEntryProjectedStrategyInstance,
) -> StrategyInstanceRuntimeState
```

The first operation step is exactly:

```text
source_state = projection.source.resolved_state.runtime_state
```

`projection.desired_entry` is the new desired value. The extracted
`source_state` is the authoritative already-loaded snapshot for current-cycle
comparison, command construction, external execution, and confirmation
application. There is no separately supplied state, so the orchestrator adds no
binding check against a second aggregate. It neither obtains another state
snapshot, copies the state into another input model, nor persists its result.

The return value has two semantic forms:

```text
NoOp
-> aggregate with no logical state transition

confirmed Apply | Replace | Cancel
-> complete replacement aggregate
```

No contract depends on the returned value having the same Python object
identity as the extracted `source_state` on `NoOp`; domain-value equivalence
and absence of a logical transition are sufficient.

**Rationale:** This gives the future closed-bar owner a small deterministic seam
that preserves the projection's existing provenance while the caller owns
coordination and state lifetime.

**Alternatives considered:** Passing state as a second independent argument
would duplicate context already retained by the projection and unnecessarily
broaden the API. Letting the nested operation load and save its own aggregate
would split one closed-bar critical section, permit stale snapshots, and
duplicate ownership already assigned to `StrategyRuntimeOrchestrator`.

### Keep sequencing explicit for all four decisions

The operation first extracts `source_state`, then calls the existing pure
decision function with:

```text
projection.desired_entry
source_state.current_trade_cycle
```

The complete application sequence is:

```text
LiveEntryProjectedStrategyInstance
-> extract exact source_state
-> decide(projection.desired_entry, source_state.current_trade_cycle)
-> optional Apply-only trade_cycle_id reservation
-> optional command construction from source_state and decision
-> optional execution_port.execute(command, source_state)
-> optional successful confirmation application to source_state
-> logically unchanged or replacement StrategyInstanceRuntimeState
```

It then follows one closed sequence:

```text
NoOp
1. Extract source_state from the projection.
2. Return without a logical state transition.
3. Do not call the ID factory, command builder, execution port, or
   confirmation applier.

Apply
1. Extract source_state from the projection.
2. Call the injected TradeCycleIdFactory exactly once.
3. Give that apply-only identity and source_state to the existing command
   builder.
4. Invoke the execution port exactly once with (command, source_state).
5. After a successful confirmation is returned, call the existing applier
   against source_state.
6. Return the replacement aggregate.

Replace
1. Extract source_state from the projection.
2. Do not call the ID factory.
3. Build the command from source_state using the identity carried by Replace.
4. Invoke the execution port exactly once with (command, source_state).
5. Apply the successful confirmation to source_state and return the
   replacement aggregate.

Cancel
1. Extract source_state from the projection.
2. Do not call the ID factory.
3. Build the command from source_state using the identity carried by Cancel.
4. Invoke the execution port exactly once with (command, source_state).
5. Apply the successful confirmation to source_state and return the
   replacement aggregate.
```

The orchestrator branches on the exact closed decision variants. It does not
recompute desired-entry equivalence, construct command fields itself, or
interpret confirmation fields that belong to the pure applier.

**Rationale:** The ordering preserves the existing division of responsibility
and makes call cardinality observable in focused tests.

**Alternative considered:** Always reserve an identity before deciding. That
wastes identities on `NoOp`, violates reuse for `Replace` and `Cancel`, and
weakens the meaning of a Runtime-owned trade-cycle identity.

### Define a transport-free execution port owned by the application package

`ports.py` defines only:

```text
EntryReconciliationExecutionPort.execute(
    command: EntryReconciliationCommand,
    source_state: StrategyInstanceRuntimeState,
) -> SuccessfulEntryConfirmation
```

The port accepts the existing reconciliation command together with the exact
state snapshot extracted from the projection and returns the existing closed
successful-confirmation union. Execution failure is represented by an
exception. There is no null, boolean, public-error result, response envelope,
HTTP status, ABI request DTO, ABI success DTO, codec, or retry method in this
contract.

The orchestrator receives the port and `TradeCycleIdFactory` through
construction. External adaptation and its production composition are not part
of this change.

**Rationale:** The application operation needs one capability—execute this
already formed reconciliation command using the operational values from the
same source snapshot—and should not inherit transport concerns.

**Alternative considered:** Inject an external client directly. That would
force the orchestrator to know request and result models and combine transport
adaptation with application sequencing.

### Keep future integration at the abstract execution seam

The pair `(command, source_state)` is intentionally sufficient for a future
adapter to integrate with the canonical ABI entry-package client.

The exact request construction, response adaptation, and transport-error
translation belong to that future adapter and are outside this capability. The
future integration target is documented separately in
`openspec/specs/abi-entry-package-client/spec.md`; this change does not copy or
redefine its transport models.

### Make successful confirmation the sole transition gate

For a command-bearing decision, the execution port is called once and must
receive the exact `(command, source_state)` pair. It must return an exact
`EntryAppliedConfirmation | EntryAbsentConfirmation`. Only then does the
orchestrator invoke `apply_success_confirmation(...)` with that same
`source_state`, the original decision, exact sent command, and returned
confirmation.

An execution exception creates no confirmation and therefore cannot reach the
applier. A port result outside the closed successful union is an invariant
failure and is rejected before invoking the applier. The pure applier remains
the authority for decision/confirmation compatibility, ownership identities,
desired-entry equivalence, source-state preconditions, and replacement
aggregate construction.

Application-layer tests cover only representative applier rejection paths:
one wrong confirmation variant and one mismatched confirmation. They prove
exception propagation, no second execution, and no replacement result. The
exhaustive variant and field-by-field invariant matrix remains exclusively in
the pure applier tests.

**Rationale:** This makes acknowledged external success the only state-change
boundary and preserves the existing fail-closed applier contract.

**Alternative considered:** Create optimistic state before execution and roll
it back on failure. That introduces a false acknowledged state and unnecessary
rollback semantics into an immutable aggregate flow.

### Propagate failures without local recovery state

Failures from decision input validation, ID creation, command construction,
execution, successful-result validation, or confirmation application propagate
to the caller. In every such path:

- the extracted source aggregate remains unmodified and
  domain-value-equivalent to its pre-call snapshot;
- no replacement aggregate is returned;
- the execution port is not retried;
- no fallback decision or command is produced;
- no pending, retry, suppression, or partial transition state is retained.

For an `Apply` execution failure, the locally reserved identity is discarded as
an unacknowledged attempt; it never creates a `CurrentTradeCycle`. Repository
save and higher-level error reporting remain caller responsibilities.

**Rationale:** This matches the current immutable, acknowledgement-driven
state model and avoids claiming reliability semantics that have not been
designed.

### Preserve one-way dependency direction

The new application package may import:

- `LiveEntryProjectedStrategyInstance`;
- `StrategyInstanceRuntimeState` for extraction and the execution-port
  signature;
- `TradeCycleIdFactory`;
- pure reconciliation decisions and decision function;
- `EntryReconciliationCommand` and `SuccessfulEntryConfirmation`;
- the existing command builder and confirmation applier;
- its own execution port.

The existing `runtime/entry_reconciliation` modules must not import the new
orchestrator package or port. The new package must have no direct import of, or
behavioral dependency on, repository, coordination, top-level orchestrator, ABI
transport, HTTP, Engine, open-position, open-trade, handoff, or infrastructure
modules.

`runtime.routing.models` remains an approved direct dependency because it owns
`LiveEntryProjectedStrategyInstance`. Its existing transitive imports of
open-position and open-trade-related model types do not violate this boundary.
Architecture checks govern direct imports and application behavior, not the
complete transitive module graph.

A future adapter may depend outward on both the application execution port and
the canonical external client contract. Neither the pure reconciliation
package nor `EntryReconciliationOrchestrator` depends back on that adapter.

**Rationale:** Application sequencing depends on stable domain capabilities;
the domain capability does not depend on its caller.

## Risks / Trade-offs

- [The port may execute externally and then fail ambiguously] → Propagate the
  exception, do not transition state or retry locally, and leave stronger
  recovery/idempotency for a separately designed boundary.
- [An `Apply` ID can be consumed without creating a cycle] → Treat IDs as
  opaque unique reservations, not a gap-free sequence; only confirmation
  creates acknowledged state.
- [The returned `NoOp` aggregate may or may not be the same Python object] →
  Specify logical equality and absence of transition, not implementation
  identity.
- [The narrow port still needs an external adapter later] → Keep that adapter
  independently testable and outside this capability.

## Migration Plan

1. Add the isolated application package and narrow execution port without
   changing existing callers.
2. Implement the single-input orchestrator by extracting its source snapshot
   from the projection and composing the current pure contracts.
3. Add focused decision, exact `(command, source_state)` call-cardinality,
   error, invariant, and architecture tests.
4. Leave production composition and the current semantic stopping point
   unchanged until a later closed-bar change adopts the operation.

Rollback removes the unused application package and its tests; no persisted
state, external contract, or production wiring migration is involved.

## Open Questions

None for this capability. Concrete external adaptation, top-level
critical-section integration, persistence, and error reporting belong to later
changes.
