## 1. Pure decision

- [ ] 1.1 Add frozen `Replace(trade_cycle_id: str, desired_entry: DesiredEntry)` to `runtime/entry_reconciliation/models.py` with the same validation as `Cancel` and `Apply`; extend `EntryReconciliationDecision` and the package exports.
- [ ] 1.2 `decide_entry_reconciliation`: a changed non-null desired entry returns `Replace(current.trade_cycle_id, new)`; null still returns `Cancel`; the frozen-context invariant is unchanged.
- [ ] 1.3 `build_entry_reconciliation_command` and `apply_success_confirmation` raise `EntryReconciliationInvariantError` for `Replace`.
- [ ] 1.4 Tests: update `test_reconciliation.py:99` (changed → `Replace`), plus the full five-row table, `Replace` validation, and builder/applier rejection of `Replace`.

## 2. Orchestrator

- [ ] 2.1 In `EntryReconciliationOrchestrator.execute`, handle `Replace(C, Y)` in eight steps:
  1. build `Cancel(C)`;
  2. save marker C;
  3. execute the cancel;
  4. require `EntryAbsentConfirmation`;
  5. apply it to get S1;
  6. reserve N;
  7. boundary save of S1 with marker N;
  8. build `Apply(Y)` with N, execute it, require `EntryAppliedConfirmation`, journal `entry_package_applied`, and return the result of `apply_success_confirmation` on the boundary state.
- [ ] 2.2 Keep `Apply`, `Cancel` and `NoOp` behaviour byte-for-byte unchanged.
- [ ] 2.3 Tests (fake port and in-memory repository):
  - success: two port calls in order, one id reservation after the cancel, the save sequence [marker C, boundary], and the final state;
  - a cancel exception or timeout: no apply, no reservation, durable cycle C with marker C;
  - a contradictory absent confirmation: invariant error, no apply;
  - an apply exception: no retry, durable boundary state;
  - an apply contradiction: invariant error, durable boundary state.

## 3. Outer flow and recovery

- [ ] 3.1 Test that `StrategyRuntimeOrchestrator.process` saves the final applied aggregate once after a replace, and that `live_entry_evaluated` stays one record per bar.
- [ ] 3.2 Resolver tests for the two durable shapes: cycle C with marker C resolves as an uncertain removal; no cycle with marker N resolves as an uncertain apply (`entry_order_not_found` clears, live adopts, filled freezes the first fill). No resolver code change is expected.
- [ ] 3.3 Test the XRP scenario: 5 consecutive bars with a changing desired entry produce a live order on every bar (one cancel plus one apply per bar after the first).
- [ ] 3.4 Test the fill race: the old order fills before the cancel, the cancel is not absent → no apply; the next bar freezes the first fill of C.
- [ ] 3.5 Update the production e2e test that expects a changed desired entry to cancel without applying.

## 4. Specs and checks

- [ ] 4.1 Update the `entry-reconciliation`, `entry-reconciliation-orchestrator` and `current-trade-cycle-state` specs per this change.
- [ ] 4.2 Run `openspec validate restore-runtime-replace-reconciliation-v1 --strict`, lint, typecheck and the unit tests. Do not run the all-families memo parity test.
