## 1. Application Package and Execution Port

- [x] 1.1 Add the isolated
  `strategy_runtime.runtime.entry_reconciliation_orchestrator` package without
  changing the existing pure `runtime/entry_reconciliation` package.
- [x] 1.2 Define `EntryReconciliationExecutionPort.execute(...)` with exactly
  `EntryReconciliationCommand` plus `StrategyInstanceRuntimeState` inputs and
  `SuccessfulEntryConfirmation` output.
- [x] 1.3 Keep null/failure result variants, HTTP and ABI DTOs, codecs,
  repository operations, coordination, retries, and production adapter details
  out of the port.
- [x] 1.4 Expose only the application operation and narrow port types required
  by future callers through the new package boundary.
- [x] 1.5 Keep `EntryReconciliationCommand` unchanged with exactly
  `strategy_instance_id`, `trade_cycle_id`, `ticker`, and `desired_entry`;
  add no operational or transport fields.

## 2. Entry Reconciliation Orchestrator

- [x] 2.1 Implement `EntryReconciliationOrchestrator` with injected
  `TradeCycleIdFactory` and `EntryReconciliationExecutionPort`, exposing
  `execute(projection)` with only one `LiveEntryProjectedStrategyInstance`
  argument.
- [x] 2.2 Extract the exact source snapshot from
  `projection.source.resolved_state.runtime_state` and accept no second
  independently supplied state or replacement input DTO.
- [x] 2.3 Use that exact extracted `source_state` for reconciliation, command
  construction, the second execution-port argument, and successful-confirmation
  application without a redundant cross-state binding check.
- [x] 2.4 Implement `NoOp` as a logical no-transition return that bypasses the
  ID factory, command builder, execution port, and confirmation applier without
  constraining Python object identity.
- [x] 2.5 Implement `Apply` ordering as exactly one ID reservation, existing
  command construction with `source_state` and that apply-only ID, exactly one
  `execute(command, source_state)` call, successful-result validation, and
  existing confirmation application against the same state.
- [x] 2.6 Implement `Replace` and `Cancel` ordering without ID reservation,
  using the identity carried by the decision through command construction,
  exactly one `execute(command, source_state)` call, successful-result
  validation, and confirmation application against the same state.
- [x] 2.7 Reject a port return outside the closed successful-confirmation union
  with `EntryReconciliationInvariantError` before invoking the applier.
- [x] 2.8 Return only the existing applier's complete replacement aggregate for
  confirmed command-bearing decisions and never construct partial or
  optimistic state in the orchestrator.

## 3. Decision and Call-Cardinality Tests

- [x] 3.1 Add a fake execution port that records both the exact command and
  exact source-state object received by every call.
- [x] 3.2 Add focused unit tests for both `NoOp` decision-table cases, asserting
  source-state extraction, logical state preservation, and zero ID, builder,
  execution, and applier calls.
- [x] 3.3 Add focused `Apply` tests proving exactly one ID-factory call, exact
  identity forwarding, one command construction, one execution call, and one
  successful-confirmation application.
- [x] 3.4 Add focused `Replace` tests proving zero ID-factory calls, reuse of
  the decision/current-cycle identity, one execution call, and replacement of
  the acknowledged package.
- [x] 3.5 Add focused `Cancel` tests proving zero ID-factory calls, reuse of the
  decision/current-cycle identity, one execution call, and clearing of the
  complete current cycle.
- [x] 3.6 Assert the execution port receives the exact command built for each
  command-bearing decision and the exact state snapshot embedded in the
  projection, and is never invoked more than once.
- [x] 3.7 Assert the orchestrator has a single-projection input signature,
  extracts no alternative state, and returns aggregate state rather than a
  decision, command, confirmation, or transport wrapper.

## 4. Error and Invariant Tests

- [x] 4.1 Test ID-factory failure and invalid reserved IDs with unchanged source
  state, no execution, no confirmation application, and propagated failure.
- [x] 4.2 Test command-builder invariant failures with unchanged source state
  and zero execution/applier calls.
- [x] 4.3 Parameterize execution exceptions for `Apply`, `Replace`, and
  `Cancel`, asserting one attempted external call, no retry, no fallback, no
  applier call, and no logical state transition.
- [x] 4.4 Test that a failed `Apply` retains no reserved-ID, pending-command, or
  partially created cycle state.
- [x] 4.5 Test a forged non-success port return is rejected before the applier
  and leaves the source aggregate unchanged.
- [x] 4.6 Test one representative wrong confirmation variant and one
  representative mismatched confirmation, asserting propagated
  `EntryReconciliationInvariantError`, no second execution-port call, no
  replacement result, and unchanged source state; rely on the pure-applier
  suite for the exhaustive variant and field-level invariant matrix.
- [x] 4.7 Use pre-call value snapshots in all failure assertions and avoid
  requiring top-level or nested Python object identity.

## 5. Architecture and Scope Tests

- [x] 5.1 Add architecture tests proving the new application package imports
  only live-entry projection, Runtime state and ID boundaries, existing pure
  reconciliation components, and its own execution port.
- [x] 5.2 Extend pure-layer architecture tests to prove
  `runtime/entry_reconciliation` does not import the new orchestrator package
  or execution port.
- [x] 5.3 Prove the new package has no direct import of or behavioral dependency
  on repository, keyed-mutex, top-level orchestrator, handoff, ABI/HTTP DTO,
  codec, client, Engine, open-position, open-trade, fill-event, bootstrap, or
  infrastructure modules.
- [x] 5.4 Prove `EntryReconciliationOrchestrator.execute(...)` performs no
  repository call or repeated state load and can acquire source state only
  through the supplied projection.
- [x] 5.5 Prove the execution port may reference
  `StrategyInstanceRuntimeState` but no ABI request/result type, and the
  orchestrator does not import a future bridge.
- [x] 5.6 Explicitly allow the direct import of
  `LiveEntryProjectedStrategyInstance` from `runtime.routing.models` and do not
  interpret that module's existing transitive model imports as direct
  application-package dependencies.
- [x] 5.7 Confirm that the execution-port signature does not prevent a future
  adapter from targeting the canonical ABI entry-package client, without
  constructing or adapting transport models in this change.
- [x] 5.8 Confirm implementation changes no existing ABI client/adapter,
  repository, mutex, routing, top-level orchestration, production composition,
  canonical OpenSpec, or system-plan behavior.

## 6. Verification

- [x] 6.1 Run focused orchestrator, port, source-state extraction,
  call-cardinality, error, invariant, and architecture tests.
- [x] 6.2 Run the complete Runtime pytest suite, Ruff lint, mypy, and scoped
  Ruff format verification for every Python file owned by this change.
- [x] 6.3 Run the repository-wide Ruff format gate and document the four
  unchanged baseline formatting failures:
  `src/strategy_runtime/runtime/abi/entry_package_codec.py`,
  `src/strategy_runtime/runtime/abi/entry_package_http.py`,
  `tests/contract/abi/test_entry_package_client.py`, and
  `tests/contract/abi/test_entry_package_openapi.py`.
- [x] 6.4 Run Python compilation checks for `src` and `tests`.
- [x] 6.5 Run strict OpenSpec validation for
  `entry-reconciliation-orchestrator-v1`.
- [x] 6.6 Run repository-wide strict OpenSpec validation.
- [x] 6.7 Run `git diff --check`.
- [x] 6.8 Audit the final diff and status to confirm that changes are limited to
  the new application package and its focused tests, with no canonical spec,
  system-plan, production wiring, top-level workflow, transport-adapter, or
  unrelated-file modification.
