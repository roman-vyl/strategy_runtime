## Context

`PositionManagementOrchestrator.execute()` calls `close_position(command)`
with no try/except and no prior durable write. A live Demo incident proved
that ABI can durably complete a pair-scoped close (`terminal_closed`) while
Runtime's HTTP client only observes a `TimeoutException` — Runtime's own
`current_trade_cycle` then stays frozen forever, and
`decide_entry_reconciliation()`'s existing fail-closed guard permanently
blocks that instance once the next bar routes it to entry reconciliation.
`runtime-pending-entry-recovery-v1` already solved the structurally identical
problem for entry mutations (`PendingEntryRecovery`, a pre-write before
dispatch, a pipeline guard, and a background resolver). This change extends
that same architecture to `ClosePosition`, reusing every existing mechanism
it can and adding only what close-specific semantics require.

## Goals / Non-Goals

**Goals:**
- Close the exact live gap: a lost/timed-out `close_position` response must
  no longer permanently freeze `current_trade_cycle`.
- Reuse `pending_entry_recovery`'s proven shape (single durable pre-write
  before the network call, pipeline guard, single background
  worker/mutex/thread) rather than inventing a second recovery mechanism.
- Prove the resolver's corrective action (re-issuing `close_position`) is
  safe under ABI's already-existing idempotency contract, with no new ABI
  endpoint or behavior required.

**Non-Goals:**
- Protection-mutation recovery (`apply_protection` timeouts) — out of scope;
  the current live defect is close-specific, and there's no pair-scoped
  positive-truth source to safely resolve an ambiguous protection amend.
- The separate ABI-side gap where a native TP/SL exchange-side closure makes
  `OpenPositionResolutionService` fail closed with `500` instead of
  answering `false` — a distinct ABI defect, its own future change.
- Any new HTTP endpoint, new background thread/scheduler, wall-clock
  recovery horizon, retry counter, or `operator_required` state.
- Changing ABI in any way. ABI's `POST .../close` idempotency (per-pair
  mutex, `terminal_closed` short-circuit, durable deterministic
  `close_order_link_id`) is the evidence base this design depends on, not
  something it modifies.

## Decisions

### 1. `PendingCloseRecovery` is a distinct sibling model, not a variant of `PendingEntryRecovery`
Both markers hold only `trade_cycle_id: str` — no action discriminator, no
timestamp, no retry counter. They are kept as separate types (not a shared
generic `PendingRecovery<Kind>`) because their resolution semantics differ
structurally: entry recovery has both an "uncertain create" (current cycle
null) and "uncertain removal" (current cycle set) case with a four-way ABI
`recovery_state` resolution table; close recovery has exactly one case
(current cycle is always set, since a Runtime-issued close only ever targets
an already-acknowledged cycle) resolved by a single idempotent re-issue, not
a read. Forcing these into one generic model would either lose the
close-only invariant ("no create case exists") or bolt an unused
discriminator onto the simpler entry model. Two small sibling fields are
cheaper to reason about than one generic field with conditional validity
rules.

### 2. Resolution re-issues the close command; it does not merely read state
Entry recovery resolves by *querying* ABI's recovery-state endpoint and
deciding from a four-way table, because at entry time Runtime does not know
whether ABI ever dispatched anything. Close recovery is different: Runtime
already knows an in-flight close was attempted with a specific,
deterministically-derivable `trade_cycle_id`. ABI's own `CloseApplicationService`
already guarantees the pair-scoped `POST .../close` call is safe to retry
verbatim:
- an already-`terminal_closed` record short-circuits with zero exchange
  query or mutation;
- an in-progress or not-yet-dispatched close re-derives every fact
  pair-scoped and fresh, and reuses the same durable, deterministic
  `close_order_link_id` rather than dispatching a second market order.

Re-issuing therefore both resolves the ambiguity *and* is the mechanism that
converges an ABI-side close that never completed — a read-only query could
tell Runtime whether the position is now flat, but could not itself finish
an ABI-side close that stalled before completion. Re-issuing subsumes a
read: the returned `PositionClosedConfirmation` (or its absence) already
answers "did it happen."

### 3. The pre-write happens inside `PositionManagementOrchestrator.execute()`, mirroring `EntryReconciliationOrchestrator` exactly
`EntryReconciliationOrchestrator.execute()` already establishes the pattern:
`state_repository.save(replace(source_state, pending_entry_recovery=...))`
before calling the execution port. `PositionManagementOrchestrator.execute()`
gets the identical shape for its `ClosePosition` branch. This keeps the
pre-write ordering guarantee co-located with the only call site that issues
`close_position`, avoids a second cross-cutting pre-write mechanism, and
means the fix is additive to an existing, already-tested code path rather
than a new abstraction layer.

Ordering guarantee: if the durable pre-write itself fails, `close_position`
is never called — an unconfirmed pre-write must not be followed by a
mutation Runtime can no longer account for.

### 4. The pipeline guard is one extended boolean condition, not a second gate
`StrategyRuntimeOrchestrator.process()`'s existing guard
(`if state.pending_entry_recovery is not None: return state`) moves to `if
state.pending_entry_recovery is not None or state.pending_close_recovery is
not None: return state`, same position (immediately after
`get_or_create`, inside the per-instance mutex, before the open-position
resolver). A pending close, like a pending entry removal, leaves
`current_trade_cycle` set while the exchange-side truth is uncertain, and an
unguarded open-position lookup against that ambiguity fails closed the same
way. Reusing the identical guard position means no new invariant needs
proving about pipeline ordering — the existing proof already covers "a
non-null recovery marker of either kind must be resolved before any
downstream component reads `current_trade_cycle`."

### 5. The existing `UncertainExchangeStateResolver`/Worker is extended, not duplicated
One background thread, one 30s poll, one `StrategyInstanceKeyedMutexRegistry`
already exists and already proves: independent per-instance resolution,
mutex parity with the orchestrator and first-fill webhook path, graceful
shutdown ordering relative to ABI client lifecycle, and safe re-entry after
restart (workers begin ticking against whatever the durable-store replay
already restored — no separate recovery step). Each tick now enumerates
`list_ids_with_pending_entry_recovery()` **and**
`list_ids_with_pending_close_recovery()` and dispatches by which marker is
set — same thread, same interval, same mutex discipline, no new scheduler.

### 6. Confirmed close clears both fields in one write; resolved close clears them in one write
`_close_position()`'s `replace(state, current_trade_cycle=None)` becomes
`replace(state, current_trade_cycle=None, pending_close_recovery=None)`.
The resolver's converged-close branch applies the identical
confirmation-application rule (same `current-trade-cycle-state` capability),
so there is exactly one code path that ever clears
`current_trade_cycle`/`pending_close_recovery` together, whether the
confirmation arrives synchronously in the orchestrator or asynchronously in
the resolver. No second clearing rule exists to drift out of sync with the
first.

### 7. Durable schema bump: `schema_version` 2 → 3, additive only
Following the proven 1→2 pattern for `pending_entry_recovery`:
`pending_close_recovery` becomes a required (nullable) envelope key at
`schema_version = 3`. Older `1`/`2` lines decode with
`pending_close_recovery = None` and are never rewritten; only a fresh
`save()` for that instance produces a `schema_version = 3` line. No file
migration, compaction, or rewrite step is needed at deploy time.

## Risks / Trade-offs

- **Re-issuing `close_position` depends entirely on ABI's idempotency proof
  holding.** If a future ABI change breaks the pair-scoped
  short-circuit/dedup guarantee, the resolver's safety argument breaks with
  it. Mitigated by this being an existing, already-relied-upon ABI contract
  (also depended on by nothing new) rather than a new assumption introduced
  by this change.
- **A resolver attempt and a synchronous orchestrator retry could in theory
  race** if an operator or future code path re-triggers close for the same
  instance while a resolver attempt is in flight. This is prevented the same
  way entry recovery prevents it: both paths acquire
  `StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)` for their
  full duration, so they cannot interleave.
- **No wall-clock horizon means a permanently-unreachable ABI leaves the
  marker pending indefinitely**, identical to today's `pending_entry_recovery`
  behavior. This is an accepted, already-shipped trade-off for V1, not a new
  one introduced here — no `operator_required` escalation state exists yet
  for either marker kind.
- **Schema bump touches every future write**, but not existing files;
  replay of mixed-version files is already proven correct by the 1/2
  precedent, and this change's tests extend that proof to include `3`.

## Correction pass (post code-review)

Three decisions were corrected after code review found real defects in the
first implementation pass; all three are still within this change's scope
(no new recovery cases, no ABI changes, no protection recovery):

1. **The resolver's close-recovery branch initially built its own
   `replace(state, current_trade_cycle=None, pending_close_recovery=None)`
   instead of reusing `apply_position_management_confirmation`** (the same
   `position_management_execution` helper `PositionManagementOrchestrator`
   calls for a synchronous close). That duplicated the canonical
   confirmation-application transition rule in a second place. Corrected:
   the resolver now builds a `ClosePosition` decision (with a synthetic
   `CloseSignal(True)` — unused by the transition itself, only by
   `apply_position_management_confirmation`'s type signature) and calls the
   same helper, so a synchronous close and an asynchronous recovery close
   apply the identical rule.
2. **The resolver's close-recovery branch caught bare `Exception`** around
   the re-issued `close_position` call, which would silently swallow
   programming errors (a `TypeError`/`AttributeError` from a bug), not just
   expected external failures. Corrected: it now catches only
   `PositionManagementExecutionError` (the existing parent of
   `PositionManagementExecutionUnavailable`/`Timeout`/`NetworkFailure`/
   `ProtocolError`/`PublicError`) — an unexpected exception now propagates to
   the worker's own per-instance exception isolation/logging, unchanged from
   how the worker already treats any other unexpected exception.
3. **The domain model technically allowed `pending_entry_recovery` and
   `pending_close_recovery` to both be non-null**, relying only on
   `StrategyRuntimeOrchestrator.process()`'s guard and the resolver's
   `if`/`elif` dispatch order to keep that combination from mattering in
   practice. Corrected: `StrategyInstanceRuntimeState.__post_init__` now
   rejects both being non-null at construction, which also fail-closes it at
   decode (decoding reconstructs the aggregate through the same
   constructor). No legitimate flow was found that needs both set at once —
   the existing pending-recovery guard already defers the entire pipeline,
   including both orchestrators' pre-writes, whenever either marker is
   already set, so neither pre-write can run while the other marker exists.
