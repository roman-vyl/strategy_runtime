## 1. Application-Level Input Model

- [ ] 1.1 Add `AbiFirstFillExecutionEvent` (frozen dataclass) carrying
  `strategy_instance_id: str`, `trade_cycle_id: str`, `first_fill_at_ms:
  int`, with the same non-empty-string / strictly-positive-integer
  validation style already used by sibling models in
  `runtime/state/models.py` and `runtime/first_fill/state_applier.py`. Do
  not add `entry_bar_open_time_ms` or any execution-phase/quantity field.
- [ ] 1.2 Place the model in a location consistent with the design's
  deferred placement decision (e.g. alongside the new orchestrator module);
  do not add it to `runtime/state/models.py` itself, which remains owned by
  the repository capability.

## 2. AbiExecutionEventOrchestrator

- [ ] 2.1 Implement `AbiExecutionEventOrchestrator.__init__(*, state_
  repository: StrategyInstanceRuntimeStateRepository, keyed_mutex_registry:
  StrategyInstanceKeyedMutexRegistry)` — no other constructor collaborator.
- [ ] 2.2 Implement `process(event: AbiFirstFillExecutionEvent) ->
  StrategyInstanceRuntimeState` exactly as sequenced in design.md and
  specs/abi-execution-event-orchestration/spec.md:
  `hold(event.strategy_instance_id)` → `state_repository.get(event.
  strategy_instance_id)` → raise `StrategyInstanceStateNotFound` if `None`
  → `apply_first_fill(state, event.trade_cycle_id, event.first_fill_at_ms)`
  → `state_repository.save(resulting_state)` only if `resulting_state is
  not state` → return the final state.
- [ ] 2.3 Confirm the implementation imports `apply_first_fill` and
  `StrategyInstanceStateNotFound` unchanged from their existing modules;
  add no new domain function, state machine, command builder, generic
  event dispatcher, event-handler registry, or application port wrapping
  `apply_first_fill`.

## 3. Orchestration Tests

- [ ] 3.1 Mutex is acquired keyed by the exact `strategy_instance_id` from
  the event (using a fake or the real `StrategyInstanceKeyedMutexRegistry`
  to assert the exact key used).
- [ ] 3.2 `state_repository.get(...)` is called only after the mutex is
  acquired (assert ordering via a fake repository/registry pair that
  records call order).
- [ ] 3.3 A missing aggregate (`get(...)` returns `None`) ends the
  operation by raising `StrategyInstanceStateNotFound`, with zero calls to
  `apply_first_fill` and zero calls to `save(...)`.
- [ ] 3.4 A successful `apply_first_fill` call that returns a distinct
  object causes exactly one `save(...)` call, and `process(...)` returns
  the object `save(...)` returned.
- [ ] 3.5 An identical retry — `apply_first_fill` returns the same `state`
  object reference — causes `process(...)` to return that same object and
  makes zero calls to `save(...)`.
- [ ] 3.6 A domain exception from `apply_first_fill`
  (`FirstFillInvariantError`, or the unwrapped `ValueError` from alignment)
  propagates from `process(...)` and results in zero calls to `save(...)`.
- [ ] 3.7 A `save(...)` exception propagates from `process(...)` unmodified,
  after exactly one save attempt.
- [ ] 3.8 The keyed mutex is released after any exception raised at any
  stage (missing state, domain exception, or save exception), proven by a
  subsequent same-key acquisition succeeding.
- [ ] 3.9 A writer invocation observes fresh state saved by a previous
  writer invocation under the same mutex and repository (simulate a prior
  save between two `process(...)` calls sharing the same repository/registry
  instances; assert the second call's `apply_first_fill` receives the
  updated aggregate).
- [ ] 3.10 Two invocations for different `strategy_instance_id` values do
  not block each other (assert both can proceed concurrently against a
  shared registry, e.g. via a blocking-then-releasing fake for one key
  while the other key's call completes independently).
- [ ] 3.11 The orchestrator makes zero calls to any Strategy Engine port,
  any ABI outbound client fake, `StrategyRuntimeOrchestrator`, or
  `EntryReconciliationOrchestrator` across every scenario above (assert via
  fakes/mocks that record zero invocations, not via absence of imports
  alone).
- [ ] 3.12 A real integration test wires the actual
  `InMemoryStrategyInstanceRuntimeStateRepository`,
  `StrategyInstanceKeyedMutexRegistry`, and `apply_first_fill` (no fakes for
  these three) through `AbiExecutionEventOrchestrator.process(...)`,
  covering: first successful freeze, identical-retry no-op, and
  conflicting-retry fail-closed, matching the exact scenarios already
  specified in `first-fill-transition`.

## 4. Proposal-Pass Verification (this change)

- [x] 4.1 `npm exec -- openspec validate
  "runtime-abi-execution-event-orchestration-v1" --type change --strict`
- [x] 4.2 `npm exec -- openspec validate --all --strict`
- [x] 4.3 `git diff --check`
- [x] 4.4 Confirm no production code, test file, existing spec, archived
  change, HTTP adapter, bootstrap module, or ABI/Strategy-Engine/MDS
  repository file is modified by this pass — only the four new files under
  `openspec/changes/runtime-abi-execution-event-orchestration-v1/`.
