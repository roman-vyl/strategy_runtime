## Context

Two smoke-test failures, traced to the same root cause:

- **ETH**: Runtime minted a new `trade_cycle_id` locally, sent CREATE, and the ABI
  response was ambiguous. `EntryReconciliationOrchestrator.execute()` propagates the
  execution-port exception before `apply_success_confirmation` ever runs
  (`entry_reconciliation_orchestrator/orchestrator.py`), so `state_repository.save()` is
  never reached. The minted id existed only as a local variable and is gone; ABI still
  durably remembers the attempt. The next bar mints an unrelated new id, leaving a ghost
  correlation on the ABI side forever.
- **BTC**: an existing trade cycle's AMEND went ambiguous; ABI recorded `status: "unknown"`.
  The next bar's `OpenPositionResolver.resolve()` issues its unconditional
  `GET open-position` for the existing `trade_cycle_id`, ABI's `unresolved` status bucket
  fails closed with `500`, `OpenPositionLookupUnavailable` propagates uncaught out of
  `StrategyRuntimeOrchestrator.process()`, and the instance is permanently stuck retrying
  the same failing GET on every subsequent bar with no recovery path.

Both are the same shape: Runtime has no durable record of "a mutation is in flight" before
the side effect, and no mechanism to resolve an ambiguous outcome independent of the
specific request that went ambiguous. The fix is not "resume the exact interrupted
command" — that requires reconstructing which step (cancel? create?) was interrupted, and
`abi-entry-cycle-recovery-v1` already demonstrates that in-place amend cannot be safely
resumed at all once exchange-canonical prices are the confirmation source of truth. The
fix that actually closes both defects is coarser and safer: durably remember which
`trade_cycle_id` is uncertain, stop competing with it, and periodically ask "what is
actually true on the exchange now?" until an answer resolves it or a horizon is reached.

## Goals / Non-Goals

**Goals:**
- Never lose a minted `trade_cycle_id` to an ambiguous CREATE outcome.
- Never let an unresolved ABI status permanently block an instance's bar path with no
  recovery mechanism.
- Resolve uncertainty on a cadence independent of market-bar arrival, since bar cadence
  and "an earlier command's outcome is now known" are unrelated events, and waiting for
  the next bar is not bounded for 1h/1d deployments.
- Bound automatic recovery to 24 hours, enforced by Runtime itself, not only by ABI's
  availability.

**Non-Goals:**
- Resuming an interrupted REPLACE. Physical replace no longer exists as a resumable
  operation; a changed desired entry is a `Cancel`, full stop, and the next bar's fresh
  reconciliation decides what (if anything) to apply next.
- A general retry/resend framework, a durable pending-operation queue distinct from
  `StrategyInstanceRuntimeState`, or a workflow/saga engine. The resolver has exactly two
  possible actions: observe, and — only when ABI reports the removal target is still
  live — resend CANCEL.
- Changing `GET open-position`'s existing fail-closed behavior on the normal bar path, or
  the first-fill webhook path. Both are untouched by this change.
- Replaying a committed bar an instance was skipped for while `pending_entry_recovery` was
  set. The instance resumes ordinary bar processing on the next eligible bar once
  resolved; a skipped bar is not retried. This is an accepted trade-off, not a gap: it is
  the same class of risk `CommittedBarOrchestrator` already accepts for any transient
  per-instance dispatch failure (`StrategyCycleDispatchOutcome`'s "attempted exactly once"
  contract, not "eventually succeeds"), extended to one additional, now-deterministic
  trigger. The reconciliation loop itself narrows this window relative to the discarded
  "resume on next bar" alternative — the window is bounded by the resolver's own polling
  interval, not by how long until the next genuine market bar, which for a 1h/1d
  deployment could otherwise be hours.

## Decisions

### 1. `pending_entry_recovery` is a two-field sibling, not a rich intent object

```
PendingEntryRecovery:
    trade_cycle_id: str
    created_at_ms: int
```

No `action` discriminator. The meaning is read from the combination of
`pending_entry_recovery` and `current_trade_cycle`:

- `pending_entry_recovery != None`, `current_trade_cycle == None` → an uncertain CREATE.
- `pending_entry_recovery != None`, `current_trade_cycle == A` → an uncertain removal of
  `A` (an explicit Cancel, or what was previously a Replace).

`desired_entry` is deliberately **not** stored here. `abi-entry-cycle-recovery-v1`'s
recovery-state response already includes the full `AppliedEntryPackage` (durably held on
the ABI side) whenever the exchange state is `entry_order_live` or `position_open` — the
two states where Runtime needs to reconstruct a `CurrentTradeCycle`. Runtime does not need
to separately remember what it originally intended to send.

`created_at_ms` is not optional simplicity — it is the one field required to make
Runtime's own 24-hour horizon backstop possible (Decision 4). Everything else about
`PendingEntryRecovery` is as small as the two smoke-test defects require.

### 2. Save-before-call is universal, not just for CREATE

The durable-write-before-external-call ordering already exists in `entry-reconciliation`'s
provisional-record discipline conceptually; this change makes it apply uniformly to every
entry-mutating ABI call, not only CREATE:

```
decide Apply / Cancel
        ↓
build command (mints a new trade_cycle_id only for Apply)
        ↓
durable save: pending_entry_recovery = {trade_cycle_id, now_ms}
        ↓
ABI call
        ↓
success → apply confirmation, clear pending_entry_recovery, durable save
ambiguous → propagate; pending_entry_recovery stays exactly as durably saved
```

This is the direct fix for the ETH defect: the identity is durable before the side effect
that could make it real, so an ambiguous CREATE can never lose it.

### 3. `Replace` collapses into `Cancel`; the execution bridge needs no change

Because `abi-entry-cycle-recovery-v1` makes ABI's physical replace CANCEL-only, a
`Replace` command built today (`desired_entry` non-null, targeting an existing cycle)
would map onto an ABI call that returns `entry_package_absent`, not
`entry_package_applied` — the exact opposite of what `entry-reconciliation`'s current
`Replace` confirmation handling expects (`EntryAppliedConfirmation` only). Keeping
`Replace` as a distinct decision variant that now accepts `EntryAbsentConfirmation` and
transitions to `current_trade_cycle = null` would be a decision variant with identical
execution semantics to `Cancel` in every respect — a distinction without a difference.
This change removes it instead: "applied desired entry changed" now decides `Cancel`
directly (`entry-reconciliation`'s four-way table becomes three-way), producing
`desired_entry: null` in the built command exactly as an explicit removal does today.

`entry_reconciliation_execution_bridge` requires **no change**: it already branches only
on whether the command's `desired_entry` is null or non-null, with no `Replace`-specific
code path (confirmed by reading `entryPackageApplicationService`'s Runtime-side bridge
counterpart) — collapsing the decision layer is invisible to the bridge, the ABI client,
and the wire codec.

A trade cycle whose entry changed reaches a fresh entry only through an entirely new
`Apply` on a later bar, with a new `trade_cycle_id` — this is already how the system
behaves today after any Cancel (`_apply()` requires `current_trade_cycle is None` as a
precondition; the id factory is invoked only for `Apply`). No new identity rule is
introduced.

### 4. Two independent 24-hour horizons, not one

`abi-entry-cycle-recovery-v1` anchors its own horizon on ABI's durable
`current_binding_started_at`. That alone is insufficient: if ABI itself (or its path to
Bybit) is unreachable for the entire 24 hours, ABI never gets to compute or return
`recovery_horizon_exceeded` — the resolver would poll into a permanent series of
transport failures with no mechanism to ever conclude "we can no longer auto-recover
this." Runtime therefore enforces its own backstop, checked locally before every ABI call:

```
if now_ms() - pending_entry_recovery.created_at_ms > HORIZON_MS:
    log_operator_alert(...)
    return  # pending untouched; instance stays blocked until operator action
```

Because `pending_entry_recovery.created_at_ms` is written before the first ABI call for
that trade cycle, and ABI's own `current_binding_started_at` is written strictly later
(before *its* first exchange call for the same generation), Runtime's backstop can fire
slightly *earlier* than ABI's own horizon logic would have. This is deliberately
conservative, not a bug to reconcile away: it never fires *later* than ABI's own horizon,
so the two checks never disagree in the unsafe direction — Runtime's ≤24h guarantee can
only end up stricter than ABI's, never looser, and it is the one enforcement point that
still holds when ABI itself is unreachable for the whole window.

### 5. The resolver only ever observes or resends CANCEL

```
UncertainExchangeStateResolver.attempt(strategy_instance_id):
    with keyed_mutex_registry.hold(strategy_instance_id):
        state = repository.get(strategy_instance_id)
        if state.pending_entry_recovery is None:
            return
        if now_ms() - state.pending_entry_recovery.created_at_ms > HORIZON_MS:
            log_operator_alert(state); return

        response = abi_recovery_client.query(strategy_instance_id,
                                              state.pending_entry_recovery.trade_cycle_id)

        match response:
          case transport/availability failure:
              return  # unchanged; retried on the next interval

          case recovery_horizon_exceeded:
              log_operator_alert(state); return  # unchanged

          case entry_order_live | position_open, if current_trade_cycle is None:
              # uncertain CREATE resolved live
              new_cycle = build CurrentTradeCycle from response.applied_entry_package
              if position_open: freeze first-fill from response fill facts
              save(current_trade_cycle=new_cycle, pending_entry_recovery=None)

          case terminal_without_fill | terminal_after_fill, if current_trade_cycle is None:
              # uncertain CREATE resolved absent (never dispatched, or dispatched then
              # cleanly terminated) — never resent; the next bar decides fresh
              save(current_trade_cycle=None, pending_entry_recovery=None)

          case terminal_without_fill | terminal_after_fill, if current_trade_cycle == A:
              # uncertain removal resolved: A is gone (never filled, or filled and closed)
              save(current_trade_cycle=None, pending_entry_recovery=None)

          case position_open, if current_trade_cycle == A:
              # the removal lost the race to a fill; A is a real position now
              save(current_trade_cycle=A unchanged, pending_entry_recovery=None)
              # the ordinary bar path's open-position lookup picks this up next bar

          case entry_order_live, if current_trade_cycle == A:
              # the only corrective action in this whole component
              abi_recovery_client.cancel(strategy_instance_id, A.trade_cycle_id)
              # pending_entry_recovery stays set; observed again next interval
```

This is deliberately not a generic retry framework: CREATE is never resent by this
component (an uncertain CREATE that resolves absent is simply forgotten, never
recreated — a stale Engine intent is not worth reviving), and the only resend this
component ever performs is CANCEL, targeted only at the one state (`entry_order_live`
while removal was intended) where ABI's own contract guarantees it is safe (ABI's
recovery-state endpoint is read-only for every other response and never causes an
exchange side effect itself).

### 6. `terminal_after_fill` for an uncertain CREATE needs no special state

If ABI resolves `terminal_after_fill` while `current_trade_cycle is None` (a CREATE that
did apply, and the resulting position has since fully closed, entirely outside Runtime's
view), the trade cycle Runtime never got to manage is already over. There is no live
position or live order to reconstruct, and nothing this change's minimal model needs to
represent beyond clearing `pending_entry_recovery` — `current_trade_cycle` simply stays
`None`, exactly as it would if the strategy had never decided to enter at all. A richer
audit record of "a cycle Runtime never saw did happen and did close" is a possible future
observability improvement, not required for this change's correctness goals.

### 7. Startup and shutdown follow the existing `CommittedBarIntakeWorker` shape

`UncertainExchangeStateResolver`'s worker is a second background thread constructed and
lifecycle-managed in `bootstrap/application.py` exactly like `CommittedBarIntakeWorker`:
own `_State` enum, `start()`/`stop_once()` with `join()`, bounded per-attempt work, no
tight busy-loop — a fixed polling interval between ticks, with no adaptive or exponential
backoff; a generic retry/backoff framework is explicitly out of scope for this V1. It reads
`pending_entry_recovery` durably restored by `JsonlStrategyInstanceRuntimeStateRepository`'s
existing startup replay — no separate recovery-of-recovery-state step exists or is needed.
Readiness does not wait for outstanding `pending_entry_recovery` to resolve; the process is
ready once its dependency graph is constructed, exactly as today. On shutdown, the resolver
stops accepting new attempts and joins any in-flight bounded attempt before the ABI HTTP
client is closed, so no in-flight attempt observes a closed-client error instead of a clean
interrupt.

## Risks / Trade-offs

- [A committed bar that arrives while an instance is blocked by `pending_entry_recovery`
  is not replayed once the instance unblocks] → Accepted; see Non-Goals. The resolver's
  own polling bounds this window far tighter than the discarded "resume on next bar"
  design would have for infrequent timeframes.
- [Collapsing `Replace` into `Cancel` means every changed desired entry now has a window
  with no live entry order between the CANCEL confirming and a later bar's fresh `Apply`]
  → Accepted; this is the same trade-off `abi-entry-cycle-recovery-v1` accepts on the ABI
  side, and Runtime does not attempt to hide or compensate for it.
- [Runtime's own 24-hour backstop duplicates ABI's horizon logic rather than only trusting
  ABI to report it] → Accepted deliberately (Decision 4); the duplication is the point —
  it is the only way the ≤24h guarantee holds when ABI itself is unreachable, not just
  when ABI is reachable but Bybit's history is stale.
- [Two independent worker threads (`CommittedBarIntakeWorker`,
  `UncertainExchangeStateResolver`) now share `StrategyInstanceKeyedMutexRegistry` with the
  first-fill webhook path] → Accepted; this is the same registry already shared between
  the bar path and the webhook path today, extended to a third caller with no new
  synchronization primitive.
