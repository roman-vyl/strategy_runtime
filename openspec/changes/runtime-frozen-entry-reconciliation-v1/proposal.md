## Why

Owner plan 2026-10-28 11:44, technical decision accepted 11:47 (thread «Перевести вход на цену закрытия свечи касания»):
in `touch_trigger` the entry order placed on the signal bar must stay as it was placed. Today Runtime reconciles the
order with every Engine projection: a null projection cancels it and a changed one replaces it. In `touch_trigger` the
Engine answers only on the signal bar, so the order would be cancelled on the very next bar.

This is step 1 of 3 (step 2 `runtime-frozen-entry-expiration-v1`: lifetime and expiry; step 3
`runtime-frozen-entry-integration-v1`: trade-cycle integration checks).

## What Changes

- New pure decision function `touch_trigger_entry_reconciliation(new_desired_entry, current_trade_cycle)` next to the
  existing `decide_entry_reconciliation`:
  - no current trade cycle: null projection → `NoOp`, desired entry → `Apply` (same as today);
  - acknowledged applied entry exists → `NoOp` whatever the Engine returns (null, equal or different plan).
  The acknowledged `DesiredEntry` and `trade_cycle_id` stay unchanged. No `Cancel` or `Replace` is produced.
- `decide_entry_reconciliation` is unchanged and remains the `ema_anchor` policy.
- `EntryReconciliationOrchestrator` receives `live_entry_mode` at construction and selects the decision function by it.
  Execution of `Apply`/`Cancel`/`Replace`, the pending-entry-recovery marker, state saving and journals are unchanged.
- Bootstrap passes `RuntimeConfig.live_entry_mode` to `EntryReconciliationOrchestrator` only.
- The Engine is still called on every closed bar (call chain unchanged).
- No new state fields: "the order is held" means the current cycle carries an acknowledged applied entry, which is already
  persisted, so restarts keep it.

## Out of scope

- Order lifetime, `order_lifetime_bars`, expiry, automatic `Cancel`/`Replace` at expiry: step 2.
- Integration scenarios with fill, recovery and restart: step 3.
- ABI order type. Engine. bbb_stack. Deployment.

## Limitation

After this change `touch_trigger` is NOT ready for a trading stack: a held order has no expiry and stays until filled or
until the cycle ends by existing mechanisms. Do not enable `touch_trigger` before step 2.

## Impact

- `src/strategy_runtime/runtime/entry_reconciliation/reconciliation.py` (+ `__init__` export),
  `runtime/entry_reconciliation_orchestrator/orchestrator.py`, `bootstrap/application.py`, unit tests.
- Specs: `entry-reconciliation`, `entry-reconciliation-orchestrator`, `runtime-production-composition` (added
  requirements only).
