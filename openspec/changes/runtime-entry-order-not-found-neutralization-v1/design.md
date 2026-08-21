## Context

Runtime's durable marker intentionally contains only `trade_cycle_id`. Whether it
represents uncertain APPLY or uncertain removal is already derived from
`current_trade_cycle`: null means APPLY; the matching cycle means removal. The background
resolver already owns the shared keyed mutex, strict ABI recovery decoder, and one
corrective CANCEL operation backed by the ordinary entry-package port.

The existing removal row calls corrective CANCEL when ABI reports
`entry_order_live`. The paired ABI change adds `entry_order_not_found`, a non-terminal
exact-identity observation designed to trigger the same revalidating CANCEL for uncertain
APPLY. ABI emits it only for a structurally ambiguous CREATE after the full existing
retry budget remains cleanly order/execution absent and aggregate-compatible, with
completion strictly inside Bybit's documented seven-day evidence window. ABI treats both
flat and same-side aggregate position as compatible because a same-side sibling may own
that exposure; opposite-side or failed/malformed aggregate evidence fails closed. ABI's
corrective CANCEL repeats that same gate before formal absence.

## Goals / Non-Goals

**Goals:**

- Add one strict decoder variant and one uncertain-APPLY action row.
- Reuse the existing bounded corrective CANCEL and exact `EntryPackageAbsent` identity
  check.
- Keep all evidence-age and retention reasoning inside ABI.
- Preserve durable-state minimality and bar-path recovery precedence.
- Allow the two pre-existing stuck markers to recover without manual state edits.

**Non-Goals:**

- Storing or resending the old desired entry.
- Adding timestamps, action kinds, retry counts, or a state migration.
- Computing age, interpreting exchange retention, or fabricating the fifth state from an
  ABI error.
- Changing uncertain-removal behavior.
- Adding an HTTP endpoint, recovery write contract, retry framework, or Engine call.
- Clearing a marker from the GET observation alone.

## Decisions

### 1. Derive the action from existing aggregate shape

When `current_trade_cycle is None`, the pending marker is uncertain APPLY, so
`entry_order_not_found` selects corrective CANCEL. When the matching current cycle is
present, it is uncertain removal and the new observation changes nothing.

This avoids adding an action discriminator to `PendingEntryRecovery`. The existing
invariant already provides the required distinction and is durably replayed today.

### 2. Reuse `AbiEntryCycleRecoveryPort.cancel(...)`

The resolver sends the pending `trade_cycle_id` through the already composed corrective
CANCEL adapter, which delegates to the existing entry-package client with
`desired_entry=None`. No new write endpoint or payload type is introduced.

This is preferred over adding a special neutralize endpoint: ABI's CANCEL already
revalidates the exact identity, cancels only if live, and under the paired ABI change
repeats the full order/execution/freshness proof before clean-empty evidence can become
formal absence.

### 3. Clear only on exact formal absence

The resolver compares both returned `strategy_instance_id` and `trade_cycle_id` with the
locked instance and pending marker. Only exact `EntryPackageAbsent` clears the marker.
Transport success, an unexpected applied result, identity mismatch, public error, or
exception changes nothing.

This preserves the existing uncertain-removal safety rule and makes the new row
idempotent across polling retries.

Runtime does not independently decide that the result is still fresh between GET and
CANCEL. Only the exact formal response is actionable; ABI owns the second freshness check
at the write boundary. If expiry occurs between calls, ABI returns a safe error and this
branch leaves the marker untouched.

### 4. Never reconstruct or resend CREATE

The fifth response carries no applied package, and the resolver's branch has no CREATE
dependency. After exact absence is saved, the current attempt ends. The next genuine bar
runs the ordinary router/reconciliation pipeline and calculates a new trade decision and
new trade-cycle identity.

This is preferred over durable desired-entry storage because a recovery marker may be
hours old and the original market signal may be invalid.

### 5. Preserve uncertain-removal dispatch table exactly

For removal, `entry_order_live` remains the only state that sends corrective CANCEL;
terminal states clear, `position_open` retains the current cycle, and the new
`entry_order_not_found` leaves state untouched. This change does not reinterpret removal
semantics merely because the decoder union grew.

## Risks / Trade-offs

- [GET observation becomes stale before CANCEL] → CANCEL performs fresh ABI-side exact
  order/execution reads and repeats the documented-retention freshness gate before formal
  absence.
- [A fill appears during neutralization] → ABI does not return formal absence; Runtime
  leaves the marker and a later recovery GET can resolve `position_open`.
- [Corrective response is lost after ABI durably confirms absence] → Runtime keeps the
  marker; a later recovery GET resolves the ABI record's durable absent status through
  existing `terminal_without_fill` behavior.
- [Repeated polling issues repeated CANCEL calls] → Each attempt sends at most one and
  exact absence completes immediately; all operations use the same identity and existing
  idempotent contract.
- [Old ABI never emits the fifth state] → Runtime-first deployment is inert and compatible;
  markers remain unchanged until ABI is upgraded.
- [A marker has aged beyond ABI's evidence window] → ABI returns no fifth state; Runtime
  applies no clock fallback and leaves the marker unchanged.

## Migration Plan

1. Deploy Runtime first so the strict decoder accepts all five states.
2. Deploy paired ABI change `abi-entry-order-not-found-recovery-v1`.
3. Do not edit the two incident markers or replay their old CREATE requests.
4. If each marker is still inside ABI's trustworthy window, observe it pass through
   fifth-state query, corrective CANCEL, exact `EntryPackageAbsent`, and durable clearing;
   otherwise verify it remains fail-closed without manual mutation.
5. Confirm the next genuine bar resumes ordinary evaluation with a newly calculated
   entry, if any.

Rollback is code-only and requires no state migration. Any unresolved marker remains
durable. A marker already cleared through formal absence remains valid cleared state;
ABI's durable absent record remains recoverable through the existing terminal outcome.
