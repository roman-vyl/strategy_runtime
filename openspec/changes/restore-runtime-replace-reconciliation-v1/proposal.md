## Why

Archived change `2026-07-26-runtime-entry-reconciliation-v1` defined the full decision table:

| new desired | applied | decision |
|---|---|---|
| null | null | NoOp |
| X | null | Apply(X) |
| X | X | NoOp |
| Y | X | Replace(C, Y) |
| null | X | Cancel(C) |

Archived change `2026-08-16-runtime-pending-entry-recovery-v1` collapsed `Replace` into `Cancel` (its tasks 1.3 and 8.3). It accepted a window with no order as a risk. That change mixed two things: the logical decision (the desired entry changed, so the old package must be replaced by the new one) and its physical execution (ABI serves only CANCEL, with no amend and no atomic cancel-and-create).

The result is visible on Bybit demo, 2026-10-18 (XRP): Engine projected a changed entry on 5 consecutive bars. Runtime alternated Cancel on one bar and Apply on the next, so an order was on the exchange only on every second bar (5 projections, 3 orders).

## What Changes

- `Replace(trade_cycle_id, desired_entry)` returns as a decision variant of pure reconciliation. A changed non-null desired entry decides `Replace`; only a null desired entry decides `Cancel`.
- `EntryReconciliationOrchestrator` executes `Replace(C, Y)` inside one bar as two existing, independently confirmed operations:
  1. CANCEL of cycle C (the existing Cancel command), confirmed by `EntryAbsentConfirmation`;
  2. a fresh APPLY of Y with a newly reserved `trade_cycle_id` N (the existing Apply command), confirmed by `EntryAppliedConfirmation`.
- The second operation starts only after the first is confirmed absent. There is one durable boundary between the two operations: a single save that clears C and sets the recovery marker to N, completed before the APPLY request reaches ABI.
- If CANCEL is not confirmed absent (timeout, network failure, protocol error, a fill race), there is no APPLY on this bar. The existing marker C and the existing `uncertain-exchange-state-resolver` path take over unchanged.
- A new `trade_cycle_id` per replaced entry is accepted. Each physical order still belongs to exactly one cycle.

Not changed:
- ABI is unchanged. There is no amend and no atomic replace; ABI still sees one independent PUT `desired_entry: null`, then one independent PUT with the new desired entry.
- The command builder, confirmation types, state applier, resolver, journal events and the HTTP contract are unchanged.

## Capabilities

### Modified Capabilities

- `entry-reconciliation`: the four-way table becomes a five-row table with `Replace`.
- `entry-reconciliation-orchestrator`: executes `Replace` as confirmed CANCEL, then a durable boundary, then a fresh APPLY.
- `current-trade-cycle-state`: a changed desired entry reaches its new cycle in the same bar through `Replace`, not only on a later bar.

## Impact

- Code: `runtime/entry_reconciliation/models.py`, `reconciliation.py`, `runtime/entry_reconciliation_orchestrator/orchestrator.py`, and their unit tests.
- Tests asserting "a changed desired entry returns Cancel" are updated: `tests/unit/runtime/entry_reconciliation/test_reconciliation.py:99`, and the orchestrator and production e2e tests.
- No ABI, Journal, Engine or frontend change. No state-schema change, because `pending_entry_recovery` already holds one `trade_cycle_id`.
