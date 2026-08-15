## Why

A smoke test exposed one architectural gap in two forms. When an ABI entry-package
mutation's outcome was ambiguous, Runtime had no durable memory of the attempt: a new
trade cycle's identity existed only as a local variable until a success response arrived,
so an ambiguous CREATE lost the cycle entirely (ABI remembered it; Runtime forgot it). An
existing trade cycle fared no better: the periodic `GET open-position` poll fails closed
with `500` for any ABI-side unresolved status, permanently blocking that instance with no
path back to a resolved state. Both are the same gap — Runtime never durably records "an
exchange mutation is in flight for this trade cycle" *before* causing the side effect, and
has no mechanism to later ask "what actually happened?" once the immediate response is
ambiguous.

This proposal is the Runtime counterpart to `abi-entry-cycle-recovery-v1`, which removes
in-place amend/atomic replace from ABI (replaced by cancel-only) and adds a bounded,
read-only recovery-state endpoint. Runtime's job is to durably remember which trade cycle
is uncertain before ever causing the ABI side effect, stop issuing new entry decisions for
that instance while it's uncertain, and resolve the uncertainty independently of market-bar
cadence — because "wait for the next bar" is not a recovery mechanism for a 1h/1d
deployment, and is not correct semantics: a market bar means "the market moved, recompute
strategy," not "an earlier command's outcome is now known."

## What Changes

- Add `pending_entry_recovery: PendingEntryRecovery | None` as a sibling of
  `current_trade_cycle` on `StrategyInstanceRuntimeState`. Before Runtime ever causes an
  ABI-side effect for a trade cycle (a new CREATE, or a CANCEL serving either an explicit
  Cancel decision or what was previously a Replace decision), it durably saves
  `pending_entry_recovery = {trade_cycle_id, created_at_ms}` first. If the ABI call
  succeeds, Runtime clears it in the same transition that applies the confirmed outcome.
  If the call is ambiguous (exception, or any outcome other than a clean success), the
  pending marker survives untouched — the trade cycle is never lost and no competing new
  entry decision is made for that instance.
- Collapse the `Replace` entry-reconciliation decision into `Cancel`. Since
  `abi-entry-cycle-recovery-v1` makes physical replace CANCEL-only on the ABI side (no
  in-place amend, no atomic cancel-and-create), a changed desired entry for an existing
  trade cycle now produces the same decision, command, and state transition as an
  explicit removal: cancel the existing binding, clear `current_trade_cycle`. A later,
  independent bar's fresh reconciliation applies whatever entry the strategy still wants,
  as an ordinary `Apply` with a new trade-cycle identity. **BREAKING**: entry
  reconciliation's decision table shrinks from four variants (`NoOp`/`Apply`/`Replace`/
  `Cancel`) to three (`NoOp`/`Apply`/`Cancel`).
- Add `UncertainExchangeStateResolver`, a background worker independent of committed-bar
  cadence, modeled on the existing `CommittedBarIntakeWorker`. On a bounded interval, it
  finds every strategy instance with a non-null `pending_entry_recovery`, and — holding
  the same `StrategyInstanceKeyedMutexRegistry` critical section normal bar processing
  and the first-fill webhook path already use — asks ABI's new recovery-state endpoint
  what actually happened, then resolves the pending marker or leaves it untouched.
- Add a narrow enumeration method to `StrategyInstanceRuntimeStateRepository`:
  `list_ids_with_pending_entry_recovery() -> tuple[str, ...]`, a read-only filter over the
  repository's already-resident in-memory index. No new durable structure is introduced;
  `pending_entry_recovery` inside the existing durable aggregate remains the only source
  of truth.
- Guard `StrategyRuntimeOrchestrator.process(...)`: when `pending_entry_recovery` is
  non-null, the normal bar path returns the current state immediately after
  `get_or_create`, **before** even calling the open-position resolver — not just before
  routing. This matters: for an uncertain removal, `current_trade_cycle` is still set, so
  an unguarded `GET open-position` call would reproduce the exact BTC-class `500` lockup
  this change exists to fix. The guard does not compete with the resolver, and does not
  fabricate a new entry decision while the trade cycle's exchange state is uncertain.
- Extend the durable JSONL codec to `schema_version = 2`: `pending_entry_recovery` becomes
  a required envelope key (`null` or an object), decoded strictly under the existing
  exact-key-set rule. `schema_version = 1` records remain readable, decoded as
  `pending_entry_recovery = null`; every new write is `schema_version = 2`. No file
  rewrite or migration step is required.
- Add a Runtime-side HTTP client for ABI's new recovery-state endpoint
  (`abi-entry-cycle-recovery-client`), following the same opaque-path-encoding,
  strict-decoding, and typed-failure conventions as the existing open-position lookup
  client.
- Enforce, on the Runtime side, an independent 24-hour recovery horizon anchored on
  `pending_entry_recovery.created_at_ms` — Runtime's own wall clock, checked *before*
  calling ABI. This is a deliberate backstop distinct from ABI's own horizon (anchored on
  its `current_binding_started_at`): if ABI or Bybit connectivity itself is down for more
  than 24 hours, ABI can never compute or return its own horizon response, and Runtime's
  guarantee that automatic recovery is bounded to 24 hours would otherwise depend entirely
  on ABI's availability rather than being a property Runtime can itself enforce. Because
  `pending_entry_recovery.created_at_ms` is written before ABI is ever contacted, and
  ABI's own `current_binding_started_at` is written strictly later (before ABI's first
  exchange call for the same mutation), Runtime's backstop can fire slightly *earlier*
  than ABI's own horizon would have. This is deliberately conservative and accepted: it
  never fires *later*, so it can only make the ≤24h guarantee stricter, never looser.
- Past the horizon (either Runtime's own backstop, or ABI's `recovery_horizon_exceeded`
  response), the resolver leaves `pending_entry_recovery` untouched and logs an
  operator-visible event. The affected instance remains blocked on the normal bar path
  indefinitely; unblocking it is an explicit operator action, out of scope for this
  change.

## Capabilities

### New Capabilities
- `pending-entry-recovery-state`: the minimal `PendingEntryRecovery` sibling aggregate
  field (`trade_cycle_id`, `created_at_ms`) and its relationship to `current_trade_cycle`.
- `uncertain-exchange-state-resolver`: the background worker that resolves
  `pending_entry_recovery` against ABI's recovery-state endpoint, independent of
  committed-bar cadence, under the shared keyed mutex.
- `abi-entry-cycle-recovery-client`: Runtime's outbound HTTP client for ABI's new
  recovery-state lookup.

### Modified Capabilities
- `entry-reconciliation`: the decision table shrinks to `NoOp`/`Apply`/`Cancel`; a changed
  desired entry now decides `Cancel`, not `Replace`.
- `entry-reconciliation-orchestrator`: `Replace`-specific handling is removed; command
  construction, execution, and confirmation application cover only `Apply`/`Cancel`.
- `current-trade-cycle-state`: the "replace the complete package after successful
  replace" transition is removed; a changed desired entry clears `current_trade_cycle`
  through the same path as `Cancel`.
- `strategy-instance-runtime-state-repository`: adds
  `list_ids_with_pending_entry_recovery()`.
- `runtime-durable-state-store`: `schema_version` gains a validated `2` in addition to the
  existing `1`; the envelope's exact-key-set gains the required `pending_entry_recovery`
  key for `2`.
- `strategy-runtime-orchestrator`: gains the pending-recovery guard before use-case
  routing.

## Impact

- Affects `src/strategy_runtime/runtime/state/models.py` (new `PendingEntryRecovery`,
  new field on `StrategyInstanceRuntimeState`), `src/strategy_runtime/runtime/state/
  repository.py` and `src/strategy_runtime/infrastructure/runtime_state/{jsonl_repository,
  codec}.py`, `src/strategy_runtime/runtime/entry_reconciliation/` (decision, command,
  confirmation, state applier), `src/strategy_runtime/runtime/entry_reconciliation_
  orchestrator/orchestrator.py`, `src/strategy_runtime/runtime/orchestrator/
  orchestrator.py`, a new `src/strategy_runtime/runtime/uncertain_exchange_state_
  resolver/` package, a new client under `src/strategy_runtime/infrastructure/abi/`, and
  `src/strategy_runtime/bootstrap/application.py` (worker composition and lifecycle).
- Does not change `open-position-resolver`, `http-abi-first-fill`,
  `first-fill-transition`, or the first-fill webhook path — this change deliberately
  leaves that source of fill truth untouched; whether polling can fully replace it is an
  explicit follow-up, not part of this change.
- Does not change `position-management-decision`, `position-management-orchestrator`, or
  the ABI position-management client.
- Depends on `abi-entry-cycle-recovery-v1` being available on the ABI side (the new
  recovery-state endpoint and the cancel-only replace behavior); this change's entry
  reconciliation collapse of `Replace` into `Cancel` assumes that ABI-side behavior.
