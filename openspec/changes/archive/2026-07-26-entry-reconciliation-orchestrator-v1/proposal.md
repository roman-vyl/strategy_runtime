## Why

Runtime already has pure entry-reconciliation decisions, command construction,
and successful-confirmation state application, but it has no application
operation that composes them with identity reservation and external execution.
That operation is the next seam between a ready live-entry projection and the
future caller-owned closed-bar workflow.

## What Changes

- Add an `EntryReconciliationOrchestrator` capability whose only operation
  `execute(...)` input is one `LiveEntryProjectedStrategyInstance` and whose
  output is logically unchanged or replacement
  `StrategyInstanceRuntimeState`.
- Extract the exact source aggregate from
  `projection.source.resolved_state.runtime_state` and use that same snapshot
  throughout reconciliation, command construction, execution, and confirmed
  state application.
- Preserve the existing one-load pipeline: the projection carries the state
  snapshot produced by the upstream repository/resolver/router flow, so the
  nested operation accepts no second state argument, input DTO, or repository
  dependency.
- Compose the existing entry-reconciliation decision, command builder,
  successful-confirmation applier, Runtime-owned `TradeCycleIdFactory`, and a
  new narrow external execution port that receives both the command and exact
  source state.
- Reserve a new trade-cycle identity only for `Apply`; reuse the decision-owned
  current-cycle identity for `Replace` and `Cancel`; perform no reservation,
  command construction, execution, or confirmation application for `NoOp`.
- Require exactly one external execution for every command-bearing decision and
  permit state transition only from its successful confirmation.
- Keep the pair `(command, source_state)` sufficient for a future adapter to
  target the canonical ABI entry-package client contract, while leaving exact
  request construction, response adaptation, and transport-error translation
  outside this capability.
- Propagate execution and invariant failures without retry, fallback,
  intermediate state, or logical mutation of the source aggregate.
- Keep production composition, the concrete ABI bridge, transport adaptation,
  repository persistence, keyed coordination, and the top-level closed-bar
  orchestrator outside this change.

## Capabilities

### New Capabilities

- `entry-reconciliation-orchestrator`: Defines the nested application operation
  that coordinates existing pure reconciliation contracts with apply-only
  identity reservation and a transport-free execution boundary receiving the
  command plus its exact source-state snapshot.

### Modified Capabilities

None. Existing canonical capabilities remain dependencies and their normative
requirements do not change.

## Impact

- Future implementation will add a Runtime application orchestrator, its narrow
  execution port, and focused unit and architecture tests.
- The operation will depend compositionally on the existing
  `entry-reconciliation`, `current-trade-cycle-state`, live-entry projection,
  and `abi-entry-package-client` contracts without changing them.
- A later closed-bar change can invoke this operation inside the
  `StrategyRuntimeOrchestrator` critical section and decide whether to save its
  returned aggregate.
- No production wiring, ABI client or DTO, HTTP adapter, repository, mutex,
  Engine integration, canonical spec, or system plan changes in this proposal.
