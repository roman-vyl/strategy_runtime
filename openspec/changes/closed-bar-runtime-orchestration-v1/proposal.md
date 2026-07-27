## Why

The current `StrategyRuntimeOrchestrator` stops after returning a typed Strategy
Engine projection, while the implemented keyed mutex and nested
`EntryReconciliationOrchestrator` are not yet composed into the closed-bar
workflow. This change closes that application-orchestration seam so one
strategy instance is serialized from state load through confirmed live-entry
application and conditional persistence.

## What Changes

- Extend the existing `StrategyRuntimeOrchestrator`; do not add another
  top-level closed-bar or projection orchestrator.
- Acquire the existing process-local keyed mutex by
  `StrategyBarProcessingUnit.strategy_instance_id` before state
  `get_or_create`, and retain it through position resolution, Strategy Engine
  projection, typed branching, optional live-entry reconciliation, and optional
  repository save.
- Branch on the existing
  `LiveEntryProjectedStrategyInstance | OpenTradeProjectedStrategyInstance`
  types. Route live-entry projections exactly once into the existing
  `EntryReconciliationOrchestrator.execute(projection)` operation, and fail
  explicitly with a typed unsupported error for open-trade projections.
- Fail closed for every unknown projection type without reconciliation, save,
  fallback, or successful dispatch.
- Save a returned aggregate exactly once only when it is not value-equal to the
  projection's embedded source aggregate; do not use Python object identity to
  infer a transition.
- Release the keyed mutex after every success or exception, including
  repository, resolver, Engine, reconciliation, unsupported-branch, unknown
  projection, and save failures.
- **BREAKING** Change
  `StrategyRuntimeOrchestrator.process(unit)` from returning an Engine
  projection to returning the final `StrategyInstanceRuntimeState`.
- Preserve `dispatch(...)` as a thin success adapter: it returns a successful
  outcome only after `process(...)` succeeds and lets every semantic exception
  propagate to the existing `CommittedBarOrchestrator` failure boundary.
- Add focused application-orchestration, save-cardinality, typed-branch,
  propagation, and same-key/different-key concurrency tests.
- Keep production handoff wiring, bootstrap composition, HTTP adapters,
  execution adaptation, URL/timeout configuration, Docker, and cross-service
  integration tests outside this change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `strategy-runtime-orchestrator`: Extend the existing semantic projection
  coordinator into the complete closed-bar application critical section,
  including keyed serialization, typed post-projection dispatch, conditional
  persistence, aggregate return, and fail-closed error propagation.

## Impact

- Future implementation will change the constructor dependencies, return type,
  control flow, errors, and focused tests of
  `strategy_runtime.runtime.orchestrator`.
- The change composes the existing state repository, open-position resolver,
  use-case router/Engine projection, keyed-mutex registry, typed projection
  models, and `EntryReconciliationOrchestrator` without moving their domain
  rules into the top-level orchestrator.
- Existing `dispatch(...)` and `CommittedBarOrchestrator` outcome ownership
  remain intact; production `StrategyCycleHandoffBoundary` wiring is deferred
  to the next integration seam.
- Canonical specs and system plans are dependencies for this proposal and are
  not edited by this change.
