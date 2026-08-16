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
actually true on the exchange now?" until positive evidence resolves it. There is no time
limit on this — only an evidentiary one: an instance stays blocked for as long as ABI
cannot positively establish what happened, however long that takes.

## Goals / Non-Goals

**Goals:**
- Never lose a minted `trade_cycle_id` to an ambiguous CREATE outcome.
- Never let an unresolved ABI status permanently block an instance's bar path with no
  recovery mechanism.
- Resolve uncertainty on a cadence independent of market-bar arrival, since bar cadence
  and "an earlier command's outcome is now known" are unrelated events, and waiting for
  the next bar is not bounded for 1h/1d deployments.
- Never resolve an uncertain trade cycle from the *absence* of exchange evidence — only
  from a positively established fact. This is the correctness backbone this change relies
  on instead of a wall-clock horizon.

**Non-Goals:**
- Any wall-clock recovery horizon. There is no time limit on `pending_entry_recovery`, no
  timestamp field on it, and no reasoning about Runtime-clock-vs-ABI-clock ordering.
  Whether a given attempt can resolve depends entirely on whether ABI can positively
  establish the trade cycle's fate right now, not on how long it has been pending.
- Automatic recovery from a long outage or restart after which the exchange evidence
  needed to establish a trade cycle's fate is no longer practically available (e.g. Bybit
  history has aged past what a definitive query can still see). An instance in that state
  remains fail-closed indefinitely; unblocking it is explicit operator/manual disaster
  recovery, entirely out of scope for this change. Automatic reconciliation is scoped to
  short-lived ambiguous exchange outcomes, not to disaster recovery.
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

### 1. `pending_entry_recovery` is a one-field sibling, not a rich intent object

```
PendingEntryRecovery:
    trade_cycle_id: str
```

No `action` discriminator, no timestamp. The meaning is read from the combination of
`pending_entry_recovery` and `current_trade_cycle`:

- `pending_entry_recovery != None`, `current_trade_cycle == None` → an uncertain CREATE.
- `pending_entry_recovery != None`, `current_trade_cycle == A` → an uncertain removal of
  `A` (an explicit Cancel, or what was previously a Replace).

`desired_entry` is deliberately **not** stored here. `abi-entry-cycle-recovery-v1`'s
recovery-state response already includes the full `AppliedEntryPackage` (durably held on
the ABI side) whenever the exchange state is `entry_order_live` or `position_open` — the
two states where Runtime needs to reconstruct a `CurrentTradeCycle`. Runtime does not need
to separately remember what it originally intended to send.

There is no `created_at_ms` and no other bookkeeping field. This change carries no wall-
clock recovery horizon (see Non-Goals and Decision 4), so there is nothing for a
timestamp to measure. `PendingEntryRecovery` is exactly as small as the two smoke-test
defects require.

### 2. Save-before-call is universal, not just for CREATE

The durable-write-before-external-call ordering already exists in `entry-reconciliation`'s
provisional-record discipline conceptually; this change makes it apply uniformly to every
entry-mutating ABI call, not only CREATE:

```
decide Apply / Cancel
        ↓
build command (mints a new trade_cycle_id only for Apply)
        ↓
durable save: pending_entry_recovery = {trade_cycle_id}
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

### 4. Absence of evidence is never treated as evidence of absence

This change carries no wall-clock recovery horizon. In its place, the single correctness
rule this whole design leans on is enforced by `abi-entry-cycle-recovery-v1`: ABI's
recovery-state endpoint returns `terminal_without_fill` or `terminal_after_fill` **only**
when it has positively established that outcome — a definitively observed
terminal-without-fill order status, or a definitively observed fill. A query that comes
back clean-but-empty everywhere it looked (no live order, no history match, no open
position) proves nothing about what actually happened — Bybit's own history could simply
no longer show the record — so ABI reports that as its existing safe-error response, the
same shape it already uses when a query fails outright, not as a resolved state.

Runtime's side of this rule is passive: the resolver never itself infers absence from any
response shape. It only ever transitions state on the four positive business states ABI
returns, and treats every other response — a transport failure, an ABI availability
failure, or ABI's own inconclusive-evidence safe error — identically: leave
`pending_entry_recovery` untouched, retry on the next tick. There is no separate
`recovery_horizon_exceeded` case to special-case, and no distinct "give up" branch beyond
"this response wasn't one of the four states, so nothing changes."

The direct consequence: if the evidence needed to positively resolve a trade cycle is
never available (a very long outage, evidence that has genuinely aged out), the instance
stays blocked indefinitely — not because of an elapsed-time check, but because the
resolver never receives anything it is permitted to act on. See Non-Goals.

### 5. The resolver only ever observes or resends CANCEL

```
UncertainExchangeStateResolver.attempt(strategy_instance_id):
    with keyed_mutex_registry.hold(strategy_instance_id):
        state = repository.get(strategy_instance_id)
        if state.pending_entry_recovery is None:
            return

        response = abi_recovery_client.query(strategy_instance_id,
                                              state.pending_entry_recovery.trade_cycle_id)

        match response:
          case transport/availability failure, or ABI's inconclusive-evidence safe error:
              return  # unchanged; retried on the next interval — see Decision 4

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
              cancel_result = abi_recovery_client.cancel(strategy_instance_id, A.trade_cycle_id)
              match cancel_result:
                case EntryPackageAbsent(strategy_instance_id, A.trade_cycle_id):  # exact identity
                    # The corrective cancel itself already positively confirmed
                    # the absence — completing immediately avoids an unnecessary
                    # later polling round (see the note below).
                    save(current_trade_cycle=None, pending_entry_recovery=None)
                case _:  # public error, transport/protocol exception, unexpected
                         # EntryPackageApplied, identity mismatch, or anything else
                    return  # unchanged; retried on the next interval
```

This is deliberately not a generic retry framework: CREATE is never resent by this
component (an uncertain CREATE that resolves absent is simply forgotten, never
recreated — a stale Engine intent is not worth reviving), and the only resend this
component ever performs is CANCEL, targeted only at the one state (`entry_order_live`
while removal was intended) where ABI's own contract guarantees it is safe (ABI's
recovery-state endpoint is read-only for every other response and never causes an
exchange side effect itself).

**Why the corrective cancel's own result — not a later recovery-state GET — clears
the marker:** the corrective cancel's `EntryPackageAbsent` response, once its identity
is checked to exactly match the instance and the pending trade cycle, is already exact
positive confirmation of the same fact a later recovery-state GET would otherwise be
waited on to independently reconfirm. Consuming it immediately avoids one unnecessary
later polling round — there is no reason to discard a success ABI has already returned
in favor of re-deriving the identical fact through a second read. (The paired ABI
capability separately guarantees that a later recovery-state GET for the same trade
cycle would itself resolve `terminal_without_fill` directly from ABI's own durable
`absent` record, without needing to requery the exchange — see
`abi-entry-cycle-recovery-v1` design.md Decision 6 — so this is a latency optimization,
not a correctness dependency: an attempt that, for whatever reason, does not observe
the corrective cancel's own result still resolves correctly on its next observation.)
The resolver still never infers success from HTTP transport completion alone — only
that one exact, formally matching `EntryPackageAbsent` confirmation clears either
field; every other outcome is left for a later attempt.

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
- [An instance whose trade cycle's fate can never be positively established (evidence has
  aged out, or a very long outage) remains fail-closed forever, with no automatic
  unblock] → Accepted; see Non-Goals. This is the direct, intended consequence of Decision
  4's evidentiary rule, not a gap — the alternative (inferring absence from silence to
  bound the wait) is exactly the false-negative risk this design refuses to take.
- [Two independent worker threads (`CommittedBarIntakeWorker`,
  `UncertainExchangeStateResolver`) now share `StrategyInstanceKeyedMutexRegistry` with the
  first-fill webhook path] → Accepted; this is the same registry already shared between
  the bar path and the webhook path today, extended to a third caller with no new
  synchronization primitive.
