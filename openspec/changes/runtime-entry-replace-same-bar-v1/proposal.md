## Why

When Engine moves the desired entry of a pending (unfilled) trade cycle, Runtime
decides `Cancel` and ABI removes the old entry package. The new desired entry is
then only placed on the next committed bar, because the cancel bar ends with
`current_trade_cycle = null`. For a whole bar the strategy has no working entry
order even though Engine wants one, so fills at the new level are missed.

ABI deliberately serves a changed entry as cancel-only (ABI
`openspec/specs/entry-package-execution/spec.md:25-39`, commit `ebfd8c4`): a new
desired entry is applied only by a later, independent PUT for a trade cycle with
no existing binding. That contract stays as it is. Runtime can make that second
PUT itself, in the same bar, once ABI has confirmed the old package is absent.

## What Changes

- After a `Cancel` that came from a **changed non-null** desired entry, and only
  when ABI confirms `entry_package_absent`, `EntryReconciliationOrchestrator`
  applies the new desired entry in the same bar as a **new trade cycle** (fresh
  `trade_cycle_id`), with a second, independent ABI call.
- Durable ordering: the absent result and the new cycle's
  `pending_entry_recovery` marker are written in one save **before** the new PUT,
  so a crash can never leave two live entry orders or lose the cancel.
- Journal: `entry_package_applied` is written only for the new cycle. No new
  event types.
- Anything other than a confirmed absence (timeout, ambiguous result, fill race
  reported by ABI) leaves the old cycle's marker in place, routes to the
  existing recovery or open-position path, and places **no** new order.
- A failed or ambiguous follow-up apply goes to the existing recovery path on
  the new cycle's marker.
- `desired_entry = None` stays cancel-only. Unchanged entry stays `NoOp`.

Out of scope: ABI, Engine, the open-position definition, recovery decisions,
the ABI timeout value, and any price-change threshold.

## Capabilities

### Modified Capabilities

- `entry-reconciliation-orchestrator`: a changed-entry `Cancel` that is
  confirmed absent is followed in the same invocation by one `Apply` for a new
  trade cycle; the source-snapshot, execute-once, replacement-state,
  durable-marker and outer-workflow requirements are restated to cover the
  two-step sequence.

## Impact

- Code: `runtime/entry_reconciliation_orchestrator/orchestrator.py` only.
  The pure `decide_entry_reconciliation`, command builder, state applier, ABI
  client, outer `StrategyRuntimeOrchestrator` and recovery resolver are
  unchanged.
- Exchange: at most two ABI entry-package calls per instance per bar, in order
  cancel then apply.
- Tests: new and updated unit tests in
  `tests/unit/runtime/entry_reconciliation_orchestrator/`.
