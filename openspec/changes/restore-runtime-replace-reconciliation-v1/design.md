## Context

- Pure decision: `runtime/entry_reconciliation/reconciliation.py` `decide_entry_reconciliation`. Today, a changed entry returns `Cancel(C)` (line 59).
- Execution: `runtime/entry_reconciliation_orchestrator/orchestrator.py` `execute`. It works in four steps:
  1. it reserves an id for `Apply`;
  2. it builds one command;
  3. it saves `pending_entry_recovery = {command.trade_cycle_id}` before the ABI call;
  4. it calls the bridge and applies the confirmation via `apply_success_confirmation`.
- The outer `StrategyRuntimeOrchestrator.process` saves the returned aggregate once, when it differs from the source.
- `uncertain-exchange-state-resolver` resolves a durable marker:
  - when `current_trade_cycle` is null, as an uncertain apply;
  - when `current_trade_cycle` is set, as an uncertain removal.
  The bar path skips an instance while any marker is set.
- ABI (`entry-package-execution`, commit ebfd8c4) serves a changed package only by CANCEL. It returns `entry_package_absent`, and a new entry is applied only by a later, independent PUT.

## Decisions

### D1. Replace is a logical decision; its execution is two confirmed operations

`Replace(trade_cycle_id=C, desired_entry=Y)` is a pure decision value. It does not imply any ABI capability. The orchestrator decomposes it into the existing `Cancel(C)` and `Apply(Y)` decisions, run in order. Each uses the existing command builder, bridge and `apply_success_confirmation`, unchanged. No new command type, confirmation type or ABI call exists.

### D2. Order and the durable boundary

Inside one `execute` call, while the outer orchestrator holds the instance's keyed mutex:

1. **Save marker C.** Save `pending_entry_recovery = {C}` on the source state (the existing pre-side-effect save).
2. **CANCEL C.** Call the bridge with the Cancel command (`desired_entry: null`).
3. **Confirm absent.** Continue only on a matching `EntryAbsentConfirmation`. Apply it with `apply_success_confirmation(Cancel)` → state S1, with `current_trade_cycle = null` and no marker.
4. **Reserve N.** Reserve a new id N via `TradeCycleIdFactory`.
5. **Boundary save.** In one durable save, write S1 with `pending_entry_recovery = {N}`. This save is the boundary between the two operations and completes before any APPLY request reaches ABI.
6. **APPLY Y.** Call the bridge with the Apply command (Y, N).
7. **Confirm applied.** On a matching `EntryAppliedConfirmation`, apply `apply_success_confirmation(Apply)` against the boundary state → S2, with cycle N, package Y and no marker. Return S2; the outer orchestrator saves it, which is the existing single final save.

The `entry_package_applied` journal record is written for N exactly as for a plain Apply. No journal event is added.

### D3. Recovery at every failure point

Each failure point reuses an existing recovery path:

| Failure point | Durable state | Who resolves it | Apply this bar? |
|---|---|---|---|
| Crash or exception before step 2 returns, or CANCEL timeout, network or protocol error | cycle C + marker C | resolver, uncertain removal (existing) | no |
| CANCEL rejected or not absent, e.g. the old order filled (fill race) | cycle C + marker C | resolver: `position_open` → first fill, otherwise terminal or absent (existing) | no |
| Contradictory absent confirmation (invariant) | cycle C + marker C | fails closed; resolver (existing) | no |
| Crash between step 3 and step 5 | cycle C + marker C (S1 was never saved) | resolver, uncertain removal → finds absent → clears C | no; the next bar decides `Apply(Y')` |
| Crash or exception after step 5, or APPLY timeout or network error | no cycle + marker N | resolver, uncertain apply for N (existing): not found → clear; live → adopt; filled → first fill | no second attempt |
| APPLY invariant failure | no cycle + marker N | resolver (existing) | no |

Rules for every row:
- The orchestrator never retries, never sends a fallback command, and never sends APPLY while the CANCEL outcome is unknown.
- A position can never hold two live entry orders from this instance. APPLY N is sent only after C is confirmed absent and that absence is durably recorded.

### D4. Accepted cost

- Between the confirmed CANCEL and the confirmed APPLY there is a short interval with no order: two sequential ABI round-trips within the same bar, instead of a whole bar as today.
- If CANCEL is ambiguous, the bar degrades to today's behaviour: no order until recovery resolves, then a fresh Apply on a later bar.

### D5. Runtime→ABI timeout (observation, not changed here)

- `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` defaults to 5 s (`docker-compose.yml:18`).
- ABI cancels were observed taking 10–17 s on demo, so a CANCEL can end as a Runtime timeout even when ABI later succeeds. Such a bar falls into the first row of D3, with no APPLY on that bar.
- Raising the timeout is a configuration decision for the owner. It is not part of this change.

## Risks

- **Two sequential ABI calls hold the instance mutex longer.** Other instances are independent (keyed mutex). The bar budget is 5 minutes.
- **One cycle id per replaced entry.** The Journal shows one `entry_package_applied` per cycle. This is accepted by the owner (a new `trade_cycle_id` is allowed).
