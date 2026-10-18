## Context

Today `EntryReconciliationOrchestrator.execute(projection)`:

1. decides with `decide_entry_reconciliation(projection.desired_entry, source_state.current_trade_cycle)`;
2. for `Apply` reserves an id from `TradeCycleIdFactory`;
3. builds the command;
4. durably saves `source_state` with `pending_entry_recovery = {command.trade_cycle_id}`;
5. calls `execution_port.execute(command, source_state)` once;
6. journals `entry_package_applied` for an `EntryAppliedConfirmation`;
7. returns `apply_success_confirmation(...)`, which clears the marker.

`decide_entry_reconciliation` returns `Cancel(current.trade_cycle_id)` both when
the new desired entry is `None` and when it differs from the acknowledged one
(`runtime/entry_reconciliation/reconciliation.py:55-59`). ABI serves a changed
non-null entry against a live binding as cancel-only and expects a separate PUT
for a fresh trade cycle (`entryPackageApplicationService.ts`
`handleNonNullDesiredEntry`). On `filled_before_cancel` and on unknown results
ABI returns an internal error, which the Runtime client turns into an
exception. The Runtime ABI timeout (`RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`,
default 5) also surfaces as an exception.

The state applier's `Apply` transition requires `current_trade_cycle is None`,
so a same-bar apply can only be built on the post-cancel absent state.

## Goals / Non-Goals

**Goals**
- Place the new desired entry in the same bar after a confirmed cancel.
- Never have two live entry orders, even across a crash.
- Reuse the existing pure decision, builder, applier, journal and recovery.

**Non-Goals**
- No change to the ABI contract (no amend, no atomic cancel-and-create).
- No change to Engine, the open-position definition, or recovery decisions.
- No new journal event types and no new state fields.
- No change to the ABI timeout value or a price-change threshold.

## Decisions

### D1. Trigger: changed non-null entry, confirmed absent

The follow-up apply runs only when **all** hold:

- the first decision is `Cancel`;
- `projection.desired_entry is not None` (so the cancel came from a change, not
  from `desired_entry = None`);
- the port returned `EntryAbsentConfirmation`, and the applier accepted it.

The orchestrator distinguishes the two cancel causes from
`projection.desired_entry`; the pure decision type is not changed.

### D2. Same-bar apply on the absent state

1. `absent_state = apply_success_confirmation(pending_state, cancel, cancel_command, absent_confirmation)`
   (`current_trade_cycle = None`, `pending_entry_recovery = None`).
2. `follow_up = decide_entry_reconciliation(projection.desired_entry, absent_state.current_trade_cycle)`,
   which is `Apply(projection.desired_entry)`. Any other result is an
   `EntryReconciliationInvariantError` (cannot happen by construction).
3. Reserve one new id from `TradeCycleIdFactory`; build the `Apply` command
   against `absent_state`.
4. **One durable save**: `replace(absent_state, pending_entry_recovery=PendingEntryRecovery(new_id))`.
5. `execution_port.execute(apply_command, absent_state)` exactly once.
6. On `EntryAppliedConfirmation`: journal `entry_package_applied` for the new
   cycle with the processing bar's open time; return the applier's replacement
   (new current cycle, marker cleared). The outer orchestrator saves it as it
   does today.

### D3. Durable save ordering

The save in D2 step 4 carries `current_trade_cycle = None` **and** the new
marker. It is the only write between the cancel confirmation and the new PUT,
and it completes before the PUT is sent. Crash analysis:

| Crash point | Durable state | Next bar |
|---|---|---|
| before cancel PUT | old cycle, marker = old id | recovery on old id |
| after cancel confirmed, before D2 save | old cycle, marker = old id | recovery finds package absent, clears; ordinary path re-applies |
| after D2 save, before/during apply PUT | no cycle, marker = new id | recovery on new id (same as a first `Apply` today) |
| after apply confirmed, before outer save | no cycle, marker = new id | recovery on new id finds the package present |

No row has two durable live bindings, and the old cycle can never be
re-cancelled after the new PUT, because the absent state is durable first.

### D4. Failures of the cancel step: no apply

Any exception from the cancel's port call (Runtime timeout, ABI internal error
from `filled_before_cancel`, unknown result, transport error) propagates as
today. The marker stays on the old cycle, no follow-up is attempted, no second
port call is made. The outer orchestrator returns early on the next bar while
the marker is set; `uncertain-exchange-state-resolver` resolves it. A fill
shows up through the existing open-position path once resolved. Invariant
errors from the applier on the cancel confirmation also propagate without a
follow-up.

### D5. Failures of the apply step: existing recovery

If the follow-up id factory, builder, or port raises, the exception propagates.
The durable state is the D2-step-4 save (no cycle, marker = new id), exactly
the shape a failed first `Apply` leaves today, so the existing recovery handles
it. If the factory or builder raises before step 4, the durable state is the
cancel's marker on the old cycle and recovery finds that package absent. No
retry and no third port call.

### D6. Journal

Only `entry_package_applied` for the new cycle. The cancel writes no event
(unchanged). `live_entry_evaluated` stays one per bar in the outer orchestrator.

### D7. Spec alignment

The current requirement "Nested operation owns no outer workflow or transport
concern" says the operation does not call repository save, which already
contradicts the shipped pre-execution marker save. This change restates it to
allow exactly the marker saves required by "Durable recovery marker is saved
before every entry mutation side effect".

## Risks / Trade-offs

- **Timeout vs ABI cancel latency.** ABI cancels currently take about 10-17 s
  against a 5 s Runtime timeout, so many replaces will time out and go to
  recovery instead of applying in the same bar. Raising the timeout is a config
  decision for the owner, outside this change.
- **Churn.** Engine moving the level by a tick every bar now produces a
  cancel plus a new order per bar instead of a cancel on one bar and an order
  on the next. A price-change threshold would damp this; it is an owner
  decision, outside this change.
- **Longer bar.** Two sequential ABI calls hold the instance mutex longer. Other
  instances are unaffected.

## Open owner decisions

1. Raise `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` above ABI cancel latency
   (otherwise replace mostly lands in recovery).
2. Whether to add a minimum price-change threshold before replacing.
