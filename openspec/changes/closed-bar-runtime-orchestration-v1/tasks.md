## 1. Orchestrator Contracts and Dependencies

- [x] 1.1 Add
  `OpenTradeProjectionUnsupportedError` and
  `UnknownStrategyProjectionError` to the existing Runtime orchestrator error
  boundary as distinct typed exceptions.
- [x] 1.2 Extend `StrategyRuntimeOrchestrator` construction with the existing
  shared `StrategyInstanceKeyedMutexRegistry` and existing
  `EntryReconciliationOrchestrator`; do not introduce another top-level
  orchestrator or replacement component protocols.
- [x] 1.3 Change
  `StrategyRuntimeOrchestrator.process(unit:
  StrategyBarProcessingUnit[DeploymentSpecification])` to return
  `StrategyInstanceRuntimeState` and update only directly affected semantic
  callers/tests and obsolete projection-return annotations.
- [x] 1.4 Preserve `dispatch(...) -> StrategyCycleDispatchOutcome` as a thin
  adapter that reports success only after `process(...)` returns and catches no
  semantic exception.

## 2. Keyed Closed-Bar Critical Section

- [x] 2.1 Enter
  `keyed_mutex_registry.hold(unit.strategy_instance_id)` before calling
  `state_repository.get_or_create(...)`.
- [x] 2.2 Keep the existing ordered pipeline—repository get-or-create,
  `OpenPositionResolver.resolve(...)`, and
  `StrategyUseCaseRouter.route(...)` including its Strategy Engine call—inside
  the same keyed context.
- [x] 2.3 Keep typed branching, live-entry reconciliation, logical-transition
  comparison, and optional save inside that context, with release delegated to
  normal context exit for both return and exception paths.
- [x] 2.4 Do not reacquire the non-reentrant mutex in
  `EntryReconciliationOrchestrator`, treat the repository's internal lock as
  workflow coordination, or move resolver/router/Engine rules into the
  top-level orchestrator.

## 3. Typed Projection Handling and State Flow

- [x] 3.1 Branch on the supported typed projection variants
  `LiveEntryProjectedStrategyInstance` and
  `OpenTradeProjectedStrategyInstance`, without string, mapping-shape,
  class-name, or attribute-presence dispatch.
- [x] 3.2 For the live-entry type, call the existing
  `EntryReconciliationOrchestrator.execute(projection)` exactly once with the
  exact router result and no second state argument.
- [x] 3.3 Compare the returned aggregate with
  `projection.source.resolved_state.runtime_state` using existing immutable
  value equality; do not use Python object identity and do not add a result DTO
  solely for `changed: bool`.
- [x] 3.4 Skip repository `save(...)` for every value-equal result; when
  the nested operation returns a complete value-different
  `StrategyInstanceRuntimeState`, save the complete aggregate exactly once and
  only then return the result of `save(...)`.
- [x] 3.5 Raise `OpenTradeProjectionUnsupportedError` for the exact open-trade
  type without nested reconciliation, save, projection return, or successful
  dispatch.
- [x] 3.6 Raise `UnknownStrategyProjectionError` for every other runtime type
  without nested reconciliation, save, fallback, or successful return.

## 4. Sequencing and Persistence Tests

- [x] 4.1 Add a test proving the real keyed lock is already held (verified by
  a non-blocking probe of the exact per-key lock, not call-order alone) at
  the moment repository state load runs.
- [x] 4.2 Prove the same real keyed lock remains held during state load,
  position resolution, router and Strategy Engine projection, live-entry
  reconciliation, and repository save, using collaborators that probe the
  real lock's hold state directly during each call.
- [x] 4.3 Prove a live-entry projection invokes the nested orchestrator exactly
  once with the exact projection object and that `process(...)` returns its
  final aggregate result.
- [x] 4.4 Test logical `NoOp` with the source aggregate itself and assert zero
  repository save calls.
- [x] 4.5 Test a distinct Python aggregate object that is value-equal to source
  and assert zero repository save calls, proving object identity is not the
  transition test.
- [x] 4.6 Test a value-different nested-operation result and assert the exact
  complete replacement is saved once, and the object returned by `save(...)`
  is returned by `process(...)`.
- [x] 4.6b Test a value-equal nested-operation result that is a different
  Python object and assert zero repository `save(...)` calls.
- [x] 4.6a Inject a fake repository whose `save(...)` returns a distinct
  `saved_state` object different from the input aggregate; assert
  `process(...)` returns the exact object returned by `save(...)`, not the
  pre-save input.
- [x] 4.7 Assert the top-level orchestrator does not reload state for
  reconciliation, pass state as a second nested-operation argument, partially
  merge aggregate fields, or reproduce nested reconciliation rules. Uses a
  fake whose `execute(self, projection)` accepts exactly one argument, so a
  second-argument call fails with `TypeError` instead of silently succeeding.

## 5. Concurrency and Release Tests

- [x] 5.1 Add a controlled two-thread test proving two invocations for the same
  exact `strategy_instance_id` never overlap and the waiter does not load state
  before the first invocation releases the key. Uses a first-arrival gate that
  blocks the lock winner mid-critical-section (after get_or_create already
  returned) plus a deterministic snapshot of the event log taken while the
  winner is gated, so a premature loser `get_or_create` call is structurally
  impossible to miss rather than timing-dependent.
- [x] 5.2 Prove a waiting same-instance invocation loads the repository state
  available after the preceding replacement save, and passes that exact
  post-save state into the resolver.
- [x] 5.3 Add a controlled two-thread test proving different strategy-instance
  IDs can hold their critical sections and progress concurrently, using a
  `threading.Barrier` both threads must reach from *inside* their own
  critical section — a wrongly shared/global lock deadlocks the barrier
  instead of merely running slower.
- [x] 5.4 Prove mutex release after a logical `NoOp` success and after a saved
  replacement success by acquiring the same key again.
- [x] 5.5 Parameterize repository get-or-create, resolver, router/Engine,
  reconciliation, and save exceptions and prove the same key can be acquired
  again after each propagated exception.
- [x] 5.6 Prove mutex release after
  `OpenTradeProjectionUnsupportedError` and
  `UnknownStrategyProjectionError`.

## 6. Typed Branch and Error-Boundary Tests

- [x] 6.1 Test exact `OpenTradeProjectedStrategyInstance` handling raises
  `OpenTradeProjectionUnsupportedError`, calls no live-entry reconciliation or
  save, returns no projection, and cannot produce successful dispatch.
- [x] 6.2 Test an unknown projection runtime type raises
  `UnknownStrategyProjectionError`, with zero reconciliation and save calls and
  no fallback.
- [x] 6.3 Test repository get-or-create, position resolver, Strategy Engine,
  entry reconciliation, and repository save errors propagate without
  translation, retry, fallback, suppression, or error-to-`NoOp` conversion.
  Uses sentinel exception instances, `exc_info.value is sentinel` identity
  assertions, and exact downstream call-count assertions per stage
  (get_or_create error: resolve=0/route=0/reconciliation=0/save=0; resolver
  error: route=0/reconciliation=0/save=0; router error:
  reconciliation=0/save=0; reconciliation error: execute=1/save=0; save
  error: save attempts=1).
- [x] 6.4 For every pre-save failure path, assert zero save calls and no partial
  replacement persistence; for save failure, assert exactly one attempted
  atomic save, no retry or compensating write, and no successful return.
- [x] 6.5 Test `dispatch(...)` returns the existing successful outcome only
  after `process(...)` succeeds and otherwise propagates the exact exception
  without constructing a failed outcome.
- [x] 6.6 Retain or extend the committed-bar orchestration test proving
  `CommittedBarOrchestrator`, not `StrategyRuntimeOrchestrator`, converts a
  propagated dispatch exception into
  `strategy_cycle_dispatch_failed`.

## 7. Architecture and Scope Guardrails

- [x] 7.1 Add or extend architecture tests proving this change modifies the
  existing Runtime orchestrator and composes only the existing repository,
  mutex, resolver, router/projection, state, and nested reconciliation
  boundaries.
- [x] 7.2 Prove `EntryReconciliationOrchestrator` remains free of keyed-mutex,
  repository get/load/save, top-level workflow, and production adapter
  ownership.
- [x] 7.3 Confirm no production `StrategyCycleHandoffBoundary` wiring,
  `bootstrap/application.py`, Strategy Engine HTTP adapter, ABI open-position
  HTTP adapter, entry-reconciliation execution adapter, Runtime URL/timeout
  configuration, Docker file, or cross-service integration test is changed.
- [x] 7.4 Confirm no canonical OpenSpec or system-plan file is changed during
  implementation.

## 8. Verification

- [x] 8.1 Run focused Runtime orchestrator sequencing, return-contract,
  save-cardinality, typed-branch, error-propagation, mutex-release, and
  concurrency tests (39 tests across `test_closed_bar_runtime_orchestration.py`,
  `test_concurrency.py`, `test_architecture.py`), and confirm each rewritten
  concurrency/sequencing proof breaks under the corresponding mutation
  (load-before-lock, release-after-load, same-instance overlap, global
  serialization of different IDs).
- [x] 8.2 Run the complete Runtime pytest suite, Ruff lint and format checks,
  mypy, and Python compilation checks using the repository's established
  verification commands.
- [x] 8.3 Run strict OpenSpec validation for
  `closed-bar-runtime-orchestration-v1`.
- [x] 8.4 Run repository-wide strict OpenSpec validation.
- [x] 8.5 Run `git diff --check`.
- [x] 8.6 Audit the final implementation diff and status to confirm the change
  is limited to application orchestration and focused tests, with every
  deferred integration seam and planning/canonical file unchanged.

## 9. Canonical Documentation Sync

- [ ] 9.1 Update the canonical `strategy-runtime-orchestrator` Purpose during
  change application/closure so it describes typed post-projection handling,
  conditional persistence, and final aggregate return rather than stopping
  before state application.
