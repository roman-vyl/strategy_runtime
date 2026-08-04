## 1. Application-Level Input Model

- [x] 1.1 Add `AbiFirstFillExecutionEvent` (frozen dataclass) carrying
  `strategy_instance_id: str`, `trade_cycle_id: str`, `first_fill_at_ms:
  int`. Validate in `__post_init__` using exact-type checks (`type(value)
  is ...`, matching the idiom already used in `runtime/state/models.py` and
  `runtime/first_fill/state_applier.py`), per
  `specs/abi-execution-event-orchestration/spec.md`: `strategy_instance_id`
  and `trade_cycle_id` each require `type(value) is str` and non-empty;
  `first_fill_at_ms` requires `type(value) is int` and `> 0` — this
  exact-type check already rejects both `bool` (a distinct `bool` type in
  Python, not `int`) and `float` without a separate branch. Do not add
  `entry_bar_open_time_ms` or any execution-phase/quantity field.
- [x] 1.2 Place the model in a location consistent with the design's
  deferred placement decision (e.g. alongside the new orchestrator module);
  do not add it to `runtime/state/models.py` itself, which remains owned by
  the repository capability.

## 2. AbiExecutionEventOrchestrator

- [x] 2.1 Implement `AbiExecutionEventOrchestrator.__init__(*, state_
  repository: StrategyInstanceRuntimeStateRepository, keyed_mutex_registry:
  StrategyInstanceKeyedMutexRegistry)` — exactly these two parameters and no
  other constructor collaborator (no Strategy Engine port, no ABI outbound
  client, no `StrategyRuntimeOrchestrator`, no
  `EntryReconciliationOrchestrator`); the class has nothing else to call.
- [x] 2.2 Implement `process(event: AbiFirstFillExecutionEvent) ->
  StrategyInstanceRuntimeState` exactly as sequenced in design.md and
  specs/abi-execution-event-orchestration/spec.md:
  `hold(event.strategy_instance_id)` → `state_repository.get(event.
  strategy_instance_id)` → raise `StrategyInstanceStateNotFound` if `None`
  → `apply_first_fill(state, event.trade_cycle_id, event.first_fill_at_ms)`
  → `state_repository.save(resulting_state)` only if `resulting_state is
  not state` → return the final state. `process(...)` invokes only these
  four steps.
- [x] 2.3 Confirm the implementation imports `apply_first_fill` and
  `StrategyInstanceStateNotFound` unchanged from their existing modules;
  add no new domain function, state machine, command builder, generic
  event dispatcher, event-handler registry, or application port wrapping
  `apply_first_fill`.

## 3. Orchestration Tests

- [x] 3.1 Mutex is acquired keyed by the exact `strategy_instance_id` from
  the event (using a fake or the real `StrategyInstanceKeyedMutexRegistry`
  to assert the exact key used).
- [x] 3.2 `state_repository.get(...)` is called only after the mutex is
  acquired (assert ordering via a fake repository/registry pair that
  records call order).
- [x] 3.3 `state_repository.get(...)` is used, and `get_or_create(...)` is
  never called, for any invocation regardless of outcome.
- [x] 3.4 A missing aggregate (`get(...)` returns `None`) ends the
  operation by raising `StrategyInstanceStateNotFound`, with zero calls to
  `apply_first_fill` and zero calls to `save(...)`.
- [x] 3.5 A successful `apply_first_fill` call that returns a distinct
  object causes exactly one `save(...)` call, and `process(...)` returns
  the object `save(...)` returned.
- [x] 3.6 An identical retry — `apply_first_fill` returns the same `state`
  object reference — causes `process(...)` to return that same object and
  makes zero calls to `save(...)`.
- [x] 3.7 A domain exception from `apply_first_fill`
  (`FirstFillInvariantError`, or the unwrapped `ValueError` from alignment)
  propagates from `process(...)` and results in zero calls to `save(...)`.
- [x] 3.8 A `save(...)` exception propagates from `process(...)` unmodified,
  after exactly one save attempt.
- [x] 3.9 The keyed mutex is released after normal completion and after any
  exception raised at any stage (missing state, domain exception, or save
  exception), proven by a subsequent same-key acquisition succeeding.
- [x] 3.10 `AbiExecutionEventOrchestrator.__init__` accepts exactly
  `state_repository` and `keyed_mutex_registry` (assert via signature
  inspection or a construction test) — no test needs to mock or assert
  zero calls against Strategy Engine, an ABI outbound client,
  `StrategyRuntimeOrchestrator`, or `EntryReconciliationOrchestrator`,
  because the orchestrator has no such collaborator to call in the first
  place.
- [x] 3.11 A real integration test wires the actual
  `InMemoryStrategyInstanceRuntimeStateRepository`,
  `StrategyInstanceKeyedMutexRegistry`, and `apply_first_fill` (no fakes for
  these three) through `AbiExecutionEventOrchestrator.process(...)`,
  covering: first successful freeze, identical-retry no-op, and
  conflicting-retry fail-closed, matching the exact scenarios already
  specified in `first-fill-transition`.

Cross-orchestrator tests (serialization or fresh-state visibility between
`AbiExecutionEventOrchestrator` and `StrategyRuntimeOrchestrator` sharing one
repository/registry instance) are explicitly not part of this change's test
scope: this change designs only `AbiExecutionEventOrchestrator` in
isolation, not the production wiring that would construct both orchestrators
together. That wiring, and its own tests, belong to a future, separate
production-composition change (see design.md, "Shared repository and shared
mutex registry").

## 4. Proposal-Pass Verification (this change)

- [x] 4.1 `npm exec -- openspec validate
  "runtime-abi-execution-event-orchestration-v1" --type change --strict`
- [x] 4.2 `npm exec -- openspec validate --all --strict`
- [x] 4.3 `git diff --check`
- [x] 4.4 Confirm no production code, test file, existing spec, archived
  change, HTTP adapter, bootstrap module, or ABI/Strategy-Engine/MDS
  repository file is modified by this pass — only the five new files under
  `openspec/changes/runtime-abi-execution-event-orchestration-v1/`
  (`.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`,
  `specs/abi-execution-event-orchestration/spec.md`).

## 5. Apply-Phase Verification (this pass)

- [x] 5.1 `ruff check` over the new source and test files — passes.
- [x] 5.2 `ruff format --check` over the new source and test files — passes
  (after one auto-format of `orchestrator.py`).
- [x] 5.3 `mypy` (strict) over
  `src/strategy_runtime/runtime/abi_execution_event/` — passes, no issues.
- [x] 5.4 `python -m compileall` over the new source and test tree — passes.
- [x] 5.5 Full `pytest` run — 776 passed, 40 of which are the new
  `tests/unit/runtime/abi_execution_event/` suite (models, orchestrator
  sequencing/persistence/error-boundary, and architecture guardrails); the
  5 pre-existing failures in `tests/contract/abi/test_entry_package_openapi.py`
  and `tests/contract/abi/test_open_position_openapi.py` are unrelated —
  they require a sibling `abi_executor_bot` checkout not present in this
  environment and fail identically on `origin/main`.
