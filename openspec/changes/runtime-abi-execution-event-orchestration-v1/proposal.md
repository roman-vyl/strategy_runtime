## Why

`first-fill-transition` (archived `2026-08-04-runtime-first-fill-state-foundation-v1`)
shipped the pure domain function `apply_first_fill(state, trade_cycle_id,
first_fill_at_ms)`: it normalizes ABI's unnormalized fill timestamp onto the
registered candle grid and freezes a `FrozenExecutedEntryContext` exactly
once per trade cycle, with idempotent retry and fail-closed conflict
handling already fully specified and implemented. Nothing in Runtime invokes
it yet. `StrategyRuntimeOrchestrator` is the only existing top-level writer
path over `StrategyInstanceRuntimeStateRepository` and
`StrategyInstanceKeyedMutexRegistry`, and it exists to drive the closed-bar
projection pipeline (get-or-create, position resolution, Engine routing,
reconciliation) — not to apply an ABI-originated execution fact arriving on
its own, asynchronous path.

This change designs the missing sequencing boundary: `AbiExecutionEventOrchestrator`,
a second top-level writer path that does nothing but acquire the shared
keyed mutex, load fresh state, call the existing `apply_first_fill`
transition, and conditionally save. It is proposal-only: no production code,
tests, or existing specs change in this pass.

## What Changes

- Add a new capability, `abi-execution-event-orchestration`, defining
  `AbiExecutionEventOrchestrator` as a thin, transport-free sequencing
  boundary: acquire the shared keyed mutex for
  `strategy_instance_id`, load fresh state via
  `StrategyInstanceRuntimeStateRepository.get(...)` (never
  `get_or_create`), fail closed with a typed error when no aggregate is
  registered, call the existing `apply_first_fill(state, trade_cycle_id,
  first_fill_at_ms)` domain transition unchanged, and save the result only
  when `apply_first_fill` returns a distinct object (using the identity
  check `resulting_state is state`, matching that transition's own
  documented no-op contract).
- Define the orchestrator's application-level input as a typed value
  carrying `strategy_instance_id`, `trade_cycle_id`, and `first_fill_at_ms`
  — the same unnormalized-timestamp field name `apply_first_fill` and the
  already-shipped `abi-open-position-lookup-client` response both use.
  `entry_bar_open_time_ms` (the Engine-facing canonical name) is
  categorically excluded from this input: it exists only after the domain
  transition normalizes the fill timestamp.
- Record, in design.md prose only (not as a normative requirement of the new
  capability spec, and not implemented or tested in this pass), that
  `AbiExecutionEventOrchestrator` and `StrategyRuntimeOrchestrator` are two
  equal top-level writer paths a future, separate production-wiring change
  must construct over one shared `StrategyInstanceRuntimeStateRepository`
  instance and one shared `StrategyInstanceKeyedMutexRegistry` instance, so
  that the two paths serialize per `strategy_instance_id` through the same
  lock, exactly as `strategy-instance-keyed-coordination` already commits to
  ("Share one registry across later writers"). This change itself designs
  only `AbiExecutionEventOrchestrator`, constructed with exactly the two
  collaborators its own sequencing needs.
- Reuse the existing `StrategyInstanceStateNotFound` error
  (`runtime/state/errors.py`) for the orchestrator's missing-aggregate
  fail-closed path rather than introduce a new exception type; its existing
  semantics ("no aggregate registered under this identity") already match
  what this orchestrator needs to report.

## Capabilities

### New Capabilities

- `abi-execution-event-orchestration`: The sequencing-only orchestrator that
  applies an ABI first-fill execution event to Runtime state under the
  shared keyed mutex and shared repository, delegating all timestamp
  normalization and freezing semantics to the existing `apply_first_fill`
  domain transition.

### Modified Capabilities

None. `first-fill-transition`, `strategy-instance-runtime-state-repository`,
and `strategy-instance-keyed-coordination` are consumed exactly as already
specified and ratified; none of their requirements change. The shared-writer
relationship with `strategy-runtime-orchestrator` is a construction-time
constraint on future production wiring, not a change to either orchestrator
capability's own existing requirements, so `strategy-runtime-orchestrator`
is also left unmodified.

## Impact

- New module surface only (not implemented in this proposal-only pass):
  an `AbiExecutionEventOrchestrator` class and its typed input value,
  expected to live alongside the existing `runtime/orchestrator/` and
  `runtime/first_fill/` packages. Exact file placement is an implementation-
  phase decision, not fixed by this proposal.
- No change to `apply_first_fill`, `align_first_fill_to_entry_bar`,
  `FirstFillInvariantError`, `StrategyInstanceRuntimeStateRepository`,
  `InMemoryStrategyInstanceRuntimeStateRepository`,
  `StrategyInstanceKeyedMutexRegistry`, `StrategyRuntimeOrchestrator`,
  `EntryReconciliationOrchestrator`, or any Strategy Engine or ABI outbound
  contract.
- Explicitly out of scope for this change: the HTTP endpoint ABI would call,
  FastAPI wiring, `create_http_app`, `bootstrap/application.py`, production
  composition wiring, any ABI-side callback sender, delivery retry, outbox,
  durable deduplication, Strategy Engine request/response changes,
  open-trade projection, handling of any fill after the first, partial-fill
  lifecycle, filled/remaining quantity, average execution price, execution
  phase, a fill ledger, MDS changes, a durable Runtime repository, or
  restart recovery. All of these are named explicitly so a future reader
  does not infer they were considered and rejected here — they were simply
  not addressed by this proposal-only pass.
