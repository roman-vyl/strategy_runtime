# Runtime ↔ ABI entry delivery map

Status: living implementation map for the live-entry half of the Runtime ↔ ABI
pipeline.

This document turns
[`runtime-abi-entry-reconciliation-master-plan.md`](runtime-abi-entry-reconciliation-master-plan.md)
into independently deliverable increments. The master plan remains the
architectural source of truth; this file tracks sequencing and implementation
progress.

Interactive views:

- [`runtime-abi-entry-delivery-map.html`](runtime-abi-entry-delivery-map.html) —
  standalone call-chain map with switchable current, closed-bar, ABI webhook,
  and delivery-increment views;
- [`runtime-abi-entry-delivery-map.fragment.html`](runtime-abi-entry-delivery-map.fragment.html) —
  editable visualization source.

The checkboxes inside the interactive view are stored locally by the browser.
The checklist below is the Git-tracked canonical progress record.

## Delivery dependency map

```mermaid
flowchart TD
    CURRENT["Implemented semantic projection contour"]
    I1["I1 · ABI entry-package client"]
    I2["I2 · Aggregate, repository, identity and mutex foundation"]
    I3["I3 · Pure entry reconciliation"]
    I4["I4 · Closed-bar reconciliation orchestration"]
    I5["I5 · ABI fill webhook and execution state machine"]
    I6["I6 · Entry/fill cross-flow E2E and guardrails"]
    OPEN_GATE["Open-trade requirements gate"]
    OPEN_IMPL["Open-trade branch design and implementation"]
    FINAL["Final full Live V1 E2E"]
    FUTURE["Stronger reliability and scale"]

    CURRENT --> I4
    I1 --> I4
    I2 --> I3
    I2 --> I4
    I2 --> I5
    I3 --> I4
    I4 --> I5
    I4 --> I6
    I5 --> I6
    I6 --> OPEN_GATE
    OPEN_GATE --> OPEN_IMPL
    OPEN_IMPL --> FINAL
    FINAL --> FUTURE
```

## Canonical implementation progress

### I1 · ABI entry-package client

- [x] Proposal, design, specification, and task plan completed.
- [x] Closed request and response DTOs implemented.
- [x] Scalar `AbiEntryPackagePort` implemented.
- [x] Bounded non-retried HTTP adapter implemented.
- [x] Strict success, public-error, transport, and protocol decoding implemented.
- [x] Fake-ABI contract tests implemented.
- [x] ABI OpenAPI conformance verification implemented for the then-approved
  contract.
- [x] Change verified and archived as
  `openspec/changes/archive/2026-07-26-abi-entry-package-client-v1`.

Exit condition: Runtime owns a tested outbound ABI client that remains
unconnected to reconciliation and production composition.

### I2 · Aggregate, repository, identity and mutex foundation

- [x] Create and approve the `runtime-entry-state-foundation-v1` OpenSpec
  change.
- [x] Add the canonical Runtime-owned strategy-instance aggregate and preserve
  the existing aggregate across rediscovery.
- [x] Replace the provisional cycle with minimal `CurrentTradeCycle`:
  `trade_cycle_id + applied_entry_package`.
- [x] Add minimal `AppliedEntryPackage`: `applied_desired_entry +
  calculated_quantity`.
- [x] Keep phases, fill state, `FrozenExecutedEntryContext`, and
  position-management state outside I2.
- [x] Add repository load and complete-aggregate save operations.
- [x] Add Runtime-owned `trade_cycle_id` factory semantics.
- [x] Add the process-local keyed-mutex registry for later writer flows.
- [x] Add aggregate, repository, identity, and mutex tests.

Exit condition: Runtime can safely load, mutate, and save one strategy-instance
aggregate inside a per-instance critical section without calling ABI.

### I3 · Pure entry reconciliation

- [x] Create, approve, implement, verify, synchronize, and archive
  `runtime-entry-reconciliation-v1`.
- [x] Define exact `DesiredEntry` equivalence.
- [x] Implement closed `NoOp`, `Apply`, `Replace`, and `Cancel` decision
  variants with payloads.
- [x] Implement command construction for present and absent entry packages using
  `EntryPackageRequest`.
- [x] Implement fail-closed acknowledgement-to-state transition rules with one
  `EntryReconciliationInvariantError`.
- [x] Preserve source-state value and avoid any state transition for `NO_OP`,
  contradictory input, unconfirmed outcomes, and transport/protocol failures
  handled later by I4.
- [x] Add exhaustive decision-table, command-builder, state-applier,
  architecture-boundary, and model-shape tests.

Exit condition: pure components can derive one command and apply one valid
acknowledgement without transport, HTTP, or composition dependencies.

### I4 · Closed-bar reconciliation orchestration

- [ ] Create and approve a dedicated OpenSpec change.
- [ ] Extend the existing `StrategyRuntimeOrchestrator`; do not introduce
  another top-level closed-bar or projection orchestrator.
- [ ] Add `EntryReconciliationOrchestrator` as the nested live-entry application
  operation.
- [ ] Make `StrategyRuntimeOrchestrator` own the keyed mutex across state load,
  ABI position lookup, Engine projection, typed branching, reconciliation,
  save, and every failure path.
- [ ] Prohibit nested mutex acquisition, repository reload, and repository save
  inside `EntryReconciliationOrchestrator`.
- [ ] Route `LiveEntryProjectedStrategyInstance` into entry reconciliation.
- [ ] Make `StrategyRuntimeOrchestrator.process(unit)` fail explicitly for
  `OpenTradeProjectedStrategyInstance`; the handoff must not record or report
  that dispatch as successful.
- [ ] Reserve a new `trade_cycle_id` for `APPLY` without creating
  `CurrentTradeCycle` before acknowledgement.
- [ ] Reuse the acknowledged cycle identity for `REPLACE` and `CANCEL`.
- [ ] Preserve state on public ABI errors, timeout, network failure, and protocol
  failure.
- [ ] Adapt the ABI wire acknowledgement to the I3 confirmation boundary:
  persist only `applied_desired_entry + calculated_quantity`.
- [ ] Require bounded timeouts for every outbound call made while holding the
  mutex.
- [ ] Require the ABI entry-package acknowledgement to complete independently
  of any Runtime webhook emitted by the same call.
- [ ] Connect `StrategyCycleHandoffBoundary.dispatch(unit)` to
  `StrategyRuntimeOrchestrator.process(unit)` in production composition.
- [ ] Complete the required Strategy Engine and ABI position-lookup production
  adapters or inject their production implementations.
- [ ] Add closed-bar integration tests through a fake ABI.
- [ ] Add a contention test proving that an ABI webhook for the same
  `strategy_instance_id` blocks while `StrategyRuntimeOrchestrator` owns the
  mutex across state load, ABI position lookup, Engine projection, and
  live-entry reconciliation.
- [ ] Prove that after the closed-bar critical section releases the mutex, the
  webhook acquires it and loads fresh repository state rather than a snapshot
  captured before waiting.
- [ ] Prove that nested entry reconciliation never reacquires the non-reentrant
  mutex.

Exit condition: one closed-bar invocation is serialized from state load through
projection and live-entry application, and it persists only a valid,
identity-bound acknowledgement.

### I5 · ABI fill webhook and execution state machine

- [ ] Confirm the ABI/Bybit cumulative quantity and average-price source.
- [ ] Create and approve a dedicated OpenSpec change.
- [ ] Define the Runtime ABI fill-event HTTP contract.
- [ ] Add the fill-event HTTP handler without direct aggregate mutation.
- [ ] Add `AbiExecutionEventOrchestrator`.
- [ ] Load state only after acquiring the shared keyed mutex.
- [ ] Validate `strategy_instance_id + trade_cycle_id`.
- [ ] Freeze executed entry context on the first fill.
- [ ] Implement partial and full fill phase transitions.
- [ ] Persist cumulative quantities, average entry price, and first/last fill
  timestamps.
- [ ] Add webhook contract and execution state-machine tests.

Exit condition: ABI partial and final fills update the matching acknowledged
cycle through the same serialized repository boundary as closed-bar
reconciliation.

### I6 · Entry/fill cross-flow E2E and guardrails

- [ ] Add reconciliation-versus-webhook contention tests.
- [ ] Add the accepted Live V1 cancel/fill race test matrix.
- [ ] Verify mutex release on every success and failure path.
- [ ] Verify bounded ABI timeouts and no automatic retries.
- [ ] Add end-to-end tests from closed-bar input through acknowledgement and fill.
- [ ] Add operational journal or metrics for reconciliation and fill outcomes.
- [ ] Enforce or verify the single-process, single-worker deployment constraint.
- [ ] Run complete pytest, Ruff, mypy, compilation, and OpenSpec validation.

Exit condition: the entry-reconciliation and fill-webhook writer paths are
verified together under the explicit Live V1 concurrency boundary. This is an
entry/fill milestone, not final full Live V1 readiness.

### Open-trade gate and final Live V1

- [ ] Define open-trade branch requirements from the first post-fill committed
  bar onward.
- [ ] Design and implement the branch without preassigning a component name.
- [ ] Replace the explicit unsupported outcome only after that implementation is
  verified.
- [ ] Run final full Live V1 E2E across entry, fills, open-trade routing, and
  position management.

Exit condition: both typed projection branches are supported before Runtime is
described as fully Live V1 ready.

## Decisions required before I4

- [x] Reconcile cancellation vocabulary for I3: a confirmed cancel uses
  `EntryPackageAbsent`.
- [x] Define the persisted I3 `AppliedEntryPackage` summary:
  `applied_desired_entry + calculated_quantity`.
- [ ] Decide whether the production Strategy Engine and ABI open-position HTTP
  adapters belong to I4 or to a prerequisite composition change.

## Explicitly deferred

- [ ] Open-trade protection and close reconciliation remains outside I1–I6 and
  is governed by the explicit gate above.
- [ ] Stop/take replacement after entry.
- [ ] Partial-entry remainder and timeout policy.
- [ ] Durable fill-event deduplication.
- [ ] Persisted pending commands and ambiguous-outcome recovery.
- [ ] Repository revisions/CAS and ABI command idempotency.
- [ ] Multi-worker, multi-replica, and distributed coordination.

## Updating this map

1. Update the canonical checklist in this Markdown file.
2. Update the corresponding step status or wording in
   `runtime-abi-entry-delivery-map.fragment.html`.
3. Regenerate `runtime-abi-entry-delivery-map.html` from the fragment with title
   `Runtime ABI Entry Delivery Map` and preserve same-origin browser storage for
   tracked checkboxes.
4. Review both files in the same change as the implementation whose status
   changed.
