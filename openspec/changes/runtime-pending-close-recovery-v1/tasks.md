## 1. Model

- [x] 1.1 Add `PendingCloseRecovery { trade_cycle_id: str }` to
  `src/strategy_runtime/runtime/state/models.py`, mirroring
  `PendingEntryRecovery`'s construction validation (reject empty
  `trade_cycle_id`).
- [x] 1.2 Add `pending_close_recovery: PendingCloseRecovery | None` field to
  `StrategyInstanceRuntimeState`.

## 2. Durable codec and repository

- [x] 2.1 Bump `JsonlStrategyInstanceRuntimeStateRepository`/`codec.py` to
  accept `schema_version` `1`, `2`, and `3`; encode every new write as `3`
  with both `pending_entry_recovery` and `pending_close_recovery` present
  (`null` or object).
- [x] 2.2 Extend the envelope exact-key-set validation for
  `schema_version = 3` to require `pending_close_recovery`; leave `1`/`2`
  decoding unchanged (no rewrite of existing lines).
- [x] 2.3 Add `PendingCloseRecovery`'s own exact-key-set/nullable-field
  validation (`trade_cycle_id` only).
- [x] 2.4 Add `list_ids_with_pending_close_recovery()` to
  `StrategyInstanceRuntimeStateRepository` (interface) and
  `JsonlStrategyInstanceRuntimeStateRepository`/
  `InMemoryStrategyInstanceRuntimeStateRepository` (implementations),
  symmetric to `list_ids_with_pending_entry_recovery()`.

## 3. Position-management orchestrator pre-write

- [x] 3.1 In `PositionManagementOrchestrator.execute()`, for a
  `ClosePosition` decision, durably save `source_state` with
  `pending_close_recovery = PendingCloseRecovery(trade_cycle_id)` before
  calling `close_position(command)`.
- [x] 3.2 Confirm the pre-write's own failure propagates without ever
  calling `close_position`.
- [x] 3.3 Confirm `close_position`'s exception (e.g. timeout) still
  propagates unchanged after the pre-write succeeds, leaving the marker in
  place for the resolver.

## 4. Confirmed-close state clearing

- [x] 4.1 In `position_management_execution/state_applier.py`'s
  `_close_position()`, extend the `replace(...)` on a matching
  `PositionClosedConfirmation` to also set `pending_close_recovery=None` in
  the same call.

## 5. Orchestrator guard extension

- [x] 5.1 Extend `StrategyRuntimeOrchestrator.process()`'s existing guard
  from `state.pending_entry_recovery is not None` to
  `state.pending_entry_recovery is not None or state.pending_close_recovery
  is not None`, same position, same early-return-without-save behavior.

## 6. Resolver and worker extension

- [x] 6.1 Extend `UncertainExchangeStateResolver` (or add a sibling method
  on it) with a close-recovery attempt: under
  `StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)`, re-issue
  `PositionManagementExecutionPort.close_position` for
  `pending_close_recovery.trade_cycle_id`.
- [x] 6.2 On a matching `PositionClosedConfirmation`, apply it via the same
  `current-trade-cycle-state` confirmation-application rule used by
  `PositionManagementOrchestrator`, clearing `current_trade_cycle` and
  `pending_close_recovery` together in one save.
- [x] 6.3 On any exception or mismatched confirmation, leave state
  unchanged and let the next tick retry.
- [x] 6.4 Confirm the resolver never calls
  `PositionManagementOrchestrator.execute`, `decide_position_management`,
  `StrategyUseCaseRouter`, or Strategy Engine as part of close recovery.
- [x] 6.5 Extend `UncertainExchangeStateResolverWorker`'s tick to also
  enumerate `list_ids_with_pending_close_recovery()` and attempt each,
  isolating exceptions per instance exactly like the existing
  entry-recovery enumeration — same thread, same interval, no new
  scheduler.

## 7. Composition

- [x] 7.1 Verify `src/strategy_runtime/bootstrap/application.py` needs no
  new wiring beyond what already constructs the shared resolver/worker and
  `PositionManagementExecutionPort` — confirm no new client or endpoint is
  introduced.

## 8. Tests

- [x] 8.1 Test A: `PositionManagementOrchestrator.execute()` pre-writes
  `pending_close_recovery` before calling `close_position`, for a
  `ClosePosition` decision.
- [x] 8.2 Test B: a failed pre-write never calls `close_position`.
- [x] 8.3 Test C: a `close_position` exception after a successful pre-write
  propagates, and `pending_close_recovery` remains durably saved.
- [x] 8.4 Test D: a matching `PositionClosedConfirmation` clears both
  `current_trade_cycle` and `pending_close_recovery` in the same state
  replacement.
- [x] 8.5 Test E: `StrategyRuntimeOrchestrator.process()` short-circuits
  (no resolver, router, Engine, or reconciliation calls; no save) when
  `pending_close_recovery` is non-null, mirroring
  `test_pending_entry_recovery_guard.py`'s `_AssertNotCalled()` pattern.
- [x] 8.6 Test F: resolver's close-recovery attempt re-issues
  `close_position` under the correct instance's mutex hold.
- [x] 8.7 Test G: resolver clears both fields on a converged
  `terminal_closed`/matching confirmation; leaves both fields untouched on
  exception or mismatch.
- [x] 8.8 Test H: durable codec round-trips `schema_version = 3` with both
  marker keys present (null and populated cases); `schema_version = 1`/`2`
  lines still decode with `pending_close_recovery = None`; a `schema_version
  = 3` line missing either marker key fails closed.

## 9. Validation

- [x] 9.1 Run the full unit test suite; confirm no regression in
  `pending_entry_recovery`-related tests.
- [x] 9.2 `openspec validate --strict` for this change.

## 10. Correction pass (post code-review)

- [x] 10.1 Resolver close-recovery reuses `apply_position_management_confirmation`
  (the canonical `position_management_execution` state-transition helper)
  instead of a second hand-rolled `replace(...)`; added a spy test proving
  the resolver calls the canonical helper.
- [x] 10.2 Narrowed resolver close-recovery exception handling from bare
  `except Exception` to `except PositionManagementExecutionError`; added
  tests for an expected execution error (marker untouched, retry next tick)
  and an unexpected programming exception (propagates, state unchanged).
- [x] 10.3 Enforced mutual exclusion of `pending_entry_recovery` and
  `pending_close_recovery` at `StrategyInstanceRuntimeState.__post_init__`
  (fail-closed at construction and decode); added model-level tests and a
  codec test for a `schema_version = 3` line with both markers non-null.
- [x] 10.4 Added a direct worker-tick regression test for close-recovery
  discovery (`list_ids_with_pending_close_recovery()` only) and a defensive
  dedup test/fix (`dict.fromkeys`) for an id returned by both enumerations.
- [x] 10.5 Added a durable restart/replay regression test: a fresh
  `JsonlStrategyInstanceRuntimeStateRepository` against the same file
  discovers a replayed `pending_close_recovery`, the resolver resolves it,
  and a second reload confirms the durably cleared state.
- [x] 10.6 Full unit suite, targeted close/entry-recovery suites, `ruff
  check`, `mypy`, and `git diff --check` all green; updated the affected
  spec deltas (`uncertain-exchange-state-resolver`,
  `pending-close-recovery-state`, `runtime-durable-state-store`) and
  `design.md` to match; re-ran `openspec validate --strict`.
