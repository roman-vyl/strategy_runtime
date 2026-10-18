## 1. Orchestrator

- [ ] 1.1 In `runtime/entry_reconciliation_orchestrator/orchestrator.py`, after
  a `Cancel` whose `EntryAbsentConfirmation` was applied, and only when
  `projection.desired_entry is not None`, run the follow-up apply on the absent
  replacement state (design D1, D2).
- [ ] 1.2 Re-decide with `decide_entry_reconciliation(projection.desired_entry, None)`;
  raise `EntryReconciliationInvariantError` if the result is not `Apply`.
- [ ] 1.3 Reserve exactly one new id, build the `Apply` command against the
  absent state, and durably save the absent state with
  `pending_entry_recovery = {new_id}` before calling the port (design D3).
- [ ] 1.4 Call the port exactly once for the follow-up; journal
  `entry_package_applied` for the new cycle only; return the applier's
  replacement.
- [ ] 1.5 Leave every cancel-step exception and every follow-up exception
  propagating unchanged, with no retry and no further port call (D4, D5).
- [ ] 1.6 No change to `decide_entry_reconciliation`, the command builder, the
  state applier, the ABI client, the outer orchestrator or the recovery
  resolver.

## 2. Tests (`tests/unit/runtime/entry_reconciliation_orchestrator/`)

- [ ] 2.1 Changed entry: cancel then apply in one `execute`; the port receives
  exactly two calls in order (cancel command for the old id with the source
  state, then apply command for a new id with the absent state); the result has
  a new current cycle with the new id and no marker.
- [ ] 2.2 Changed entry, save ordering: the repository records the save with
  `current_trade_cycle = None` and marker = new id before the second port call.
- [ ] 2.3 Changed entry, journal: exactly one `entry_package_applied`, for the
  new cycle and the processing bar.
- [ ] 2.4 Ambiguous cancel (port raises on the cancel, e.g. timeout): the
  exception propagates, the port was called once, the id factory was not
  called, the durable marker stays on the old cycle, no journal event.
- [ ] 2.5 Fill race (port raises as ABI's internal error for
  `filled_before_cancel`): same as 2.4, no apply.
- [ ] 2.6 Follow-up apply raises: the exception propagates after exactly two
  port calls; the last durable save is no cycle plus marker = new id.
- [ ] 2.7 Unchanged entry: `NoOp`, no port call, no save.
- [ ] 2.8 `desired_entry = None`: cancel only, exactly one port call, result has
  no current cycle, id factory not called.
- [ ] 2.9 Update `test_changed_desired_entry_also_decides_cancel_and_sends_no_desired_entry`
  to the two-call sequence; keep the existing cancel-only test on
  `desired_entry = None`.

## 3. Validation

- [ ] 3.1 `npm run openspec:validate`.
- [ ] 3.2 Run the entry-reconciliation-orchestrator and outer orchestrator unit
  suites and the repo's lint and typecheck.
