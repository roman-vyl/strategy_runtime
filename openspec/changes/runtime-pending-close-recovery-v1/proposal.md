## Why

A live Demo acceptance run proved a gap in exactly the same distributed-mutation-ambiguity
class that `runtime-pending-entry-recovery-v1` already closed for entry mutations, but for
`ClosePosition`: under real network latency (ABI's own pair-scoped close took ~8.6s while
Runtime's HTTP client timeout fired earlier), ABI durably closed the exchange exposure
(entry neutralized, native protection neutralized, own remaining exposure closed,
`terminal_closed` durably recorded) while Runtime received only a `TimeoutException`.
`PositionManagementOrchestrator.execute()` propagates that exception uncaught, so
`StrategyRuntimeOrchestrator.process()` never reaches `state_repository.save(...)`; Runtime's
own `current_trade_cycle` stays exactly as it was before the attempt — frozen, non-null. On
the next committed bar, ABI's pair-scoped `open-position` correctly answers `false` (the
position really is closed), so Runtime routes to entry-reconciliation, where
`decide_entry_reconciliation()` finds a frozen `current_trade_cycle` and — correctly, by its
own existing invariant — fails closed forever with
`EntryReconciliationInvariantError("entry reconciliation is fail-closed once the trade
cycle's entry is frozen")`. The affected instance is permanently stuck with no path back to
normal orchestration.

## What Changes

- Add `PendingCloseRecovery { trade_cycle_id: str }` as a new sibling durable field of
  `current_trade_cycle` on `StrategyInstanceRuntimeState`, alongside the existing
  `pending_entry_recovery` — not a variant of it. `PositionManagementOrchestrator.execute()`
  durably saves `pending_close_recovery` on the current state **before** dispatching
  `close_position(command)`, mirroring `EntryReconciliationOrchestrator.execute()`'s existing
  pre-write ordering exactly. If the durable save itself fails, no close mutation is ever
  sent.
- On a synchronous, confirmed close, `_close_position()` (`position_management_execution/
  state_applier.py`) clears both `current_trade_cycle` and `pending_close_recovery` in the
  same `replace(...)`, so a single `state_repository.save(...)` converges both fields
  together. Successful synchronous close never waits on, or depends on, the recovery worker.
- Extend `StrategyRuntimeOrchestrator.process()`'s existing pending-recovery guard from
  `state.pending_entry_recovery is not None` to
  `state.pending_entry_recovery is not None or state.pending_close_recovery is not None` —
  same single check, same position (immediately after `get_or_create`, inside the existing
  per-instance mutex, before the ABI open-position lookup, before Strategy Engine, before
  either reconciliation orchestrator). No second gate abstraction.
- Extend the existing `UncertainExchangeStateResolver`/`UncertainExchangeStateResolverWorker`
  (same single background thread, same 30s poll, same
  `StrategyInstanceKeyedMutexRegistry`) to also discover and resolve
  `pending_close_recovery` markers. Resolution action for an unresolved close is proven safe
  by ABI's own `CloseApplicationService` contract (already read from source): the pair-scoped
  `POST .../close` endpoint is idempotent and safe to re-issue with the identical
  `trade_cycle_id` — an already-`terminal_closed` record short-circuits with zero exchange
  query; an in-progress or not-yet-dispatched close re-derives every fact fresh and
  pair-scoped and reuses a durable, deterministic `close_order_link_id` rather than
  re-dispatching a second market order. The resolver therefore **re-issues the close command**
  (not merely a read) as its recovery action; the response (`terminal_closed` vs. still
  incomplete/ambiguous) determines whether the marker durably clears.
- Bump the durable JSONL schema/codec analogous to the existing `schema_version` 1→2
  migration this repository already has a proven pattern for: `pending_close_recovery`
  becomes a required (nullable) envelope key; older rows decode it as `null`. No file
  rewrite or migration step required.
- Extend `StrategyInstanceRuntimeStateRepository`'s enumeration
  (`list_ids_with_pending_entry_recovery`) with a symmetric read for close markers, reused by
  the same single worker tick — no second scheduler, no second thread.

## Capabilities

### New Capabilities
- `pending-close-recovery-state`: the minimal `PendingCloseRecovery` sibling aggregate field
  (`trade_cycle_id` only) and its relationship to `current_trade_cycle`, mirroring
  `pending-entry-recovery-state`'s existing shape for a structurally different mutation class
  (close, not create/cancel).

### Modified Capabilities
- `position-management-orchestrator`: gains the pre-write-before-dispatch ordering guarantee
  for `ClosePosition`, mirroring `entry-reconciliation-orchestrator`'s existing pattern.
- `current-trade-cycle-state`: the confirmed-close state transition also durably clears
  `pending_close_recovery` in the same write that clears `current_trade_cycle`.
- `strategy-runtime-orchestrator`: the existing pending-recovery guard is extended to also
  check `pending_close_recovery`.
- `uncertain-exchange-state-resolver`: gains a close-recovery resolution path (retry the
  pair-scoped close command; converge on `terminal_closed`; leave the marker untouched on any
  inconclusive/ambiguous outcome), reusing the existing worker/thread/mutex.
- `strategy-instance-runtime-state-repository`: adds a `pending_close_recovery` enumeration
  method symmetric to the existing entry one.
- `runtime-durable-state-store`: `schema_version` gains a new validated value; the envelope's
  exact-key-set gains the required `pending_close_recovery` key.

## Impact

- Affects `src/strategy_runtime/runtime/state/models.py`,
  `src/strategy_runtime/runtime/state/repository.py`,
  `src/strategy_runtime/infrastructure/runtime_state/{jsonl_repository,codec}.py`,
  `src/strategy_runtime/runtime/position_management_execution/state_applier.py`,
  `src/strategy_runtime/runtime/position_management_orchestrator/orchestrator.py`,
  `src/strategy_runtime/runtime/orchestrator/orchestrator.py`,
  `src/strategy_runtime/runtime/uncertain_exchange_state_resolver/{resolver,worker}.py`, and
  `src/strategy_runtime/bootstrap/application.py` (composition only — reuses the existing
  worker/resolver instances and the existing `PositionManagementExecutionPort`/ABI
  position-management client; no new client, no new HTTP endpoint on either side).
- Does not change ABI. ABI's `POST .../close` and `GET .../open-position` contracts are used
  exactly as they already exist; their idempotency/pair-scoped-truth properties are the
  evidence base for this proposal, not something this change modifies.
- Does not change `apply_protection`/protection recovery — the current live defect is
  close-specific; the existing pair-scoped `open-position` truth cannot positively confirm an
  ambiguous protection-amend outcome, so extending recovery to protection is explicitly out
  of scope pending its own evidence.
- Does not address the separately-confirmed, ABI-side gap where a native-TP/SL exchange-side
  closure (own fill proven historically, aggregate now flat) makes ABI's `open-position`
  resolution fail closed with `500` rather than answer `false` — that is a distinct ABI-side
  defect in `OpenPositionResolutionService`'s aggregate-veto rule, requiring its own separate
  investigation and change, not bundled here.
- Does not add a second background worker, a wall-clock recovery horizon, a retry counter, or
  an `operator_required` state, consistent with the existing entry-recovery philosophy this
  proposal extends rather than replaces.
