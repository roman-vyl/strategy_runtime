## Context

`I4d` (`runtime-live-entry-production-composition-v1`, archived
`2026-07-30-runtime-live-entry-production-composition-v1`) wired
`HttpxAbiOpenPositionLookupAdapter` into `build_application`'s production
graph against the pre-alignment contract:
`GET /v1/strategy-instances/{strategy_instance_id}/open-position`, returning
`entry_bar_open_time_ms`/`executed_entry_price`. That contract was never
authoritative — it predates ABI's own implementation. The authoritative ABI
open-position contract shipped afterward, in `abi_executor_bot`, archived as
`abi-open-position-lookup-v1` at commit
`ea5a18903f28d89f5f97a6b9a8c82ae395bf720a`:

```text
GET /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position
```

reading directly from
`../abi_executor_bot/docs/openapi/abi-open-position-lookup-api-v1.json` (this
design was written by loading that exact document, not from Runtime-side
fixtures). ABI's own proposal.md states this plainly: *"The already
-implemented Runtime client uses an older instance-only path and field
names and needs its own coordinated change, which is out of scope here."*
This change is that coordinated change.

ABI's own design.md explains why the path is pair-addressed rather than
identity-only: the route performs a single direct
`EntryPackageCorrelationRepository.get(strategy_instance_id, trade_cycle_id)`
composite lookup — the exact same key the entry-package PUT route already
writes under — and explicitly excludes "any lookup or index keyed on
`strategy_instance_id` alone" and "any notion of a 'current trade cycle'
pointer" from its own scope. A missing record is classified as an
**ownership/invariant mismatch** (`422 unknown_trade_cycle_binding`), never
as a closed position.

Runtime's current, ratified `open-position-resolver` capability was built
against the pre-alignment identity-only assumption: it performs one
unconditional ABI lookup "without filtering by local lifecycle condition",
explicitly including the case where `state.current_trade_cycle is None`. A
pair-addressed contract cannot satisfy that requirement literally — there is
no `trade_cycle_id` to place in the path when no trade cycle has been
created yet. This was resolved, in an `/opsx:explore` pass preceding this
proposal, as a **trade-cycle-conditional lookup**: call ABI only once a
`trade_cycle_id` exists.

## Goals / Non-Goals

**Goals:**

- Align the Runtime ABI open-position client, its nearest domain models, and
  every dependent test with the exact authoritative ABI OpenAPI contract —
  path, both success variants, and every documented error status with its
  exact per-code schema.
- Replace the resolver's unconditional identity-only lookup with a
  trade-cycle-conditional one, and state precisely what Live V1 lifecycle
  assumption that rests on.
- Prove, with a real happy-path E2E test, that a closed local result (no
  ABI call) still reaches the Strategy Engine live-entry route exactly as
  before.
- Add one authoritative cross-repository contract test that fails if the
  Runtime client and the published ABI OpenAPI document ever diverge again.
- Close a short, unrelated list of small I4d documentation/config gaps
  found while re-reading the archived change against the current
  repository, without touching the archived change's own historical record.

**Non-Goals:**

- Restart recovery, a "find the position ABI still remembers" mechanism, or
  any identity-only fallback lookup. Live V1 explicitly does not claim
  restart-safe continuation of a lost `current_trade_cycle`; see
  `docs/system-plans/runtime-durable-state-repository-backlog.md`, which
  already defers durable persistence to a separate, later change and states
  "loss of in-memory state on restart is an accepted test limitation."
- Durable repository, distributed locking, or startup reconciliation
  against the exchange.
- Any new open-trade lifecycle, position-management redesign, or change to
  `EntryReconciliationOrchestrator`'s decision rules (`NoOp`/`Apply`/
  `Replace`/`Cancel`).
- Timestamp normalization, candle-grid alignment, or any computation that
  derives one timestamp from another. `first_fill_at_ms` is carried through
  to Engine's existing `entry_bar_open_time_ms` field unchanged in value —
  this change does not decide, and explicitly defers, whether that
  pass-through is Engine's long-term contract; it only keeps today's
  pre-existing pass-through behavior honest under the renamed source field.
- Any ABI-side or Strategy-Engine-side implementation change.
- Rewriting or silently marking-complete any historical record inside
  `openspec/changes/archive/2026-07-30-runtime-live-entry-production
  -composition-v1/` (see Decision "Documentation sync without rewriting
  I4d's history" below).

## Decisions

### Trade-cycle-conditional resolver: skip ABI with no current trade cycle, call ABI with the existing one otherwise

```text
state.current_trade_cycle?
  None    -> no ABI call; PositionResolvedStrategyInstanceRuntimeState(
               position_open=False, first_fill_at_ms=None,
               average_entry_price=None) -> live-entry routing
  present -> OpenPositionLookupRequest(strategy_instance_id,
               trade_cycle_id=current_trade_cycle.trade_cycle_id)
             -> ABI GET .../trade-cycles/{id}/open-position
```

This is not a heuristic or an optimization — it is the only request shape
the resolver can construct when no trade cycle exists, because
`OpenPositionLookupRequest.trade_cycle_id` has no value to carry. It is also
exactly the integration pattern ABI's own design assumes: their mental model
is PUT-creates-the-record, GET-reads-the-record, always in that order, never
the reverse.

**Correctness for the "genuinely first bar" case.** `current_trade_cycle`
becomes non-`None` only after `EntryReconciliationOrchestrator` decides
`Apply` and `AbiEntryPackageExecutionBridge` sends the entry-package PUT —
the same call that creates ABI's `EntryPackageCorrelationRepository` record.
Runtime never sends a `trade_cycle_id` to ABI through any other path. So if
`current_trade_cycle is None`, ABI cannot have a record for this strategy
instance either, by construction — there is nothing to ask about, not merely
nothing Runtime chooses to ask about.

**Accepted gap for the "restart amnesia" case.** The same local condition
(`current_trade_cycle is None`) is also what a restarted Runtime observes
after losing a previously acknowledged trade cycle from its non-durable
in-memory repository. Under the pre-alignment identity-only contract, this
case was recoverable in principle (ask ABI by identity alone). Under the
authoritative pair-addressed contract, it is not: Runtime has also lost the
one value (`trade_cycle_id`) it would need to ask ABI anything. This is a
real reduction in what this capability can prove, not a Runtime engineering
gap to close here — restart-safe continuation was already not promised by
Live V1 (see Non-Goals), and closing it requires the deferred durable-state
change, not a different open-position lookup strategy.

**Alternative considered — reserve a `trade_cycle_id` before Apply, purely to
enable an earlier lookup.** Rejected: ABI's `EntryPackageCorrelationRepository`
record is created by the entry-package PUT route, not by any separate
reservation call; a pre-reserved ID unknown to ABI would still resolve to
`unknown_trade_cycle_binding` if queried before the first PUT, so this buys
nothing and adds a second identity-generation path.

**Alternative considered — keep calling the old identity-only endpoint in
parallel/fallback.** Rejected: the old endpoint does not exist in the
authoritative ABI implementation; there is nothing to fall back to.

### unknown_trade_cycle_binding is a resolver-level state-divergence failure, decoded generically at the wire layer

The wire adapter and codec decode `unknown_trade_cycle_binding` the same way
as the other two documented `422` codes: a typed
`OpenPositionLookupPublicError` with `code` preserved, no special-casing by
value at that layer — consistent with the existing precedent from `I4c`
("other documented codes remain generic `...PublicError` instances with
`code` preserved; adding more specific subtypes is a future decision").

The *meaning* of that specific code — "the resolver called ABI about a pair
it believed was registered, and ABI disagrees" — is a resolver-level
interpretation, not a wire fact, so the new "Resolver treats an ABI-reported
trade-cycle-binding divergence as a fail-closed failure" requirement lives in
`open-position-resolver`, not `abi-open-position-lookup-client`. Mechanically
this requires no resolver code beyond *not* catching the exception: the
existing `OpenPositionResolver.resolve` already lets every `AbiOpenPosition
LookupPort` exception propagate uncaught, so this requirement is primarily a
test-coverage and documentation commitment (prove the specific divergence
scenario, not just the generic public-error scenario) rather than new
control flow.

**Alternative considered — a dedicated
`OpenPositionTradeCycleBindingDivergence` exception type.** Rejected for this
change: the ABI OpenAPI already classifies this as an ordinary documented
`422` business code alongside the other two, Runtime's existing typed-error
propagation already guarantees it is never coerced into `position_open=
false`, and a new subtype would be speculative given no caller currently
needs to branch on this specific code differently from the other two public
-error codes. If a future change needs to react to this divergence
specifically (for example, an operational alert), introducing the subtype
then is cheap and does not require touching this change's contract.

### Field propagation stops at the router's existing pass-through, not at a new Engine contract decision

`PositionResolvedStrategyInstanceRuntimeState.entry_bar_open_time_ms` /
`.executed_entry_price` rename to `.first_fill_at_ms` / `.average_entry_price`
one-for-one. The only existing reader beyond the resolver itself is
`StrategyUseCaseRouter`'s open-trade branch
(`OpenTradeProjectionRequest(..., entry_bar_open_time_ms=resolved.
entry_bar_open_time_ms, ...)`), which becomes
`entry_bar_open_time_ms=resolved.first_fill_at_ms`. `OpenTradeProjectionRequest
.entry_bar_open_time_ms` is Engine's own wire field name (part of the
`executed_trade_receipt` envelope defined by the Strategy Engine contract,
encoded by `infrastructure/strategy_engine/wire_codec.py`) and is unrelated
to ABI's field naming; it is not renamed. The router passes the value
through unchanged today (no normalization exists at this call site before
this change, and none is introduced by it) — this change only updates which
renamed source attribute that pass-through reads from.

This propagation boundary is deliberately narrow: it does not reach into
`wire_codec.py`, the Engine port models, or any Engine-side contract
question about what `entry_bar_open_time_ms` should mean for an
exchange-timestamped fill versus a candle-boundary timestamp — that question
is explicitly out of scope (see Non-Goals) and, practically, moot for this
change's testable surface, since `StrategyRuntimeOrchestrator` always raises
`OpenTradeProjectionUnsupportedError` immediately after routing regardless
of what the open-trade Engine call returns (existing, unchanged behavior).

### Codec rewrite follows the authoritative document's exact per-code shape, not a uniform envelope

The pre-alignment codec used one uniform error envelope (`{error: {code,
message, details?}}`, `details` always optional) across every status. The
authoritative document does not: `validation_failed` requires a non-empty
`details` array of `{path, message}` objects; `unknown_trade_cycle_binding`
and `unsupported_exchange_scope` forbid a `details` field entirely
(`additionalProperties: false` with only `code`+`message` in their
`properties`); `500 internal_error` also forbids `details`. The rewritten
codec enforces these per-code shapes exactly, rather than a single relaxed
schema that would silently accept a `details` field ABI never sends for two
of the three `422` codes and both would-be `500` codes.

`400` is no longer a documented status for this endpoint at all; the
rewritten codec no longer treats it as a public-error status (an
undocumented `400` becomes `OpenPositionLookupProtocolError`, like any other
undocumented status, matching the existing "never coerce an unconfirmed
outcome" rule).

`first_fill_at_ms` tightens from "non-negative" (pre-alignment, matching the
old `entry_bar_open_time_ms >= 0` domain check) to "strictly positive"
(`exclusiveMinimum: 0` in the authoritative schema) — a fill timestamp of
exactly `0` is not a valid Unix-millisecond fill time and the authoritative
document rejects it explicitly.

**Alternative considered — keep the codec's error handling uniform and just
treat `details` as always-optional for every code.** Rejected: this would
silently accept a spec-violating response (a `details` field ABI's
authoritative implementation never emits for two of the three `422` codes)
without surfacing it as a protocol error, weakening exactly the contract
-drift detection this alignment exists to restore.

### Documentation sync without rewriting I4d's history

Re-reading the archived `2026-07-30-runtime-live-entry-production
-composition-v1` change against the current repository surfaced three small,
unrelated gaps: `config/runtime.env.example` never received the five `I4d`
outbound variables; `runtime-master-plan.md` and
`runtime-abi-entry-delivery-map.md` (plus its generated HTML fragments)
still describe `I4d` as pending/`NEXT`; and that archived change's own
`tasks.md` §11 still shows unchecked "documentation sync and archive"
checkboxes with the note "not performed by this pass — awaiting an explicit
request", even though the change was, in fact, subsequently archived (a
later, separate commit performed the spec sync and archival without going
back to check those boxes).

This change fixes the *current* system-plan and config-example files going
forward, and treats them as ordinary documentation edits belonging to this
change (they are unrelated in content to the open-position alignment, but
small enough that opening a third, dedicated change purely to check three
boxes was judged not worth the process overhead). It does **not** edit any
file under `openspec/changes/archive/2026-07-30-runtime-live-entry
-production-composition-v1/`: that directory is I4d's historical record of
what was and was not done *during that change*, and editing it now to mark
§11 complete would misrepresent history — the doc sync genuinely did not
happen as part of I4d's own implementation pass. `tasks.md` in *this* change
instead performs the deferred work and references the archived change by
name, so a future reader can see who closed the gap and when, without the
archived record itself being altered.

**Alternative considered — go back and check the boxes in the archived
`I4d` tasks.md.** Rejected as history-rewriting: those checkboxes are a
record of what happened at archive time, not a live task list; editing them
now would make it look like the doc sync was part of `I4d`'s own
verification pass when it was not.

### Remove the empty duplicate change scaffold as a mechanical cleanup, not a design decision

`openspec/changes/runtime-production-composition-i4d-v1/` was created by an
earlier, now-superseded attempt (within this same working session) to
re-propose `I4d` from scratch before discovering it was already implemented
and archived on a separate branch/commit. It contains zero files (confirmed
via `ls -la`) and is untracked by Git (confirmed via `git status
--porcelain`), so there is no content or history to preserve. Removing it is
listed in tasks.md as a plain filesystem cleanup step, gated on re
-confirming both facts (empty, untracked) at implementation time in case
repository state has changed since this design was written.

## Risks / Trade-offs

- [The trade-cycle-conditional resolver cannot detect "Runtime forgot a real
  ABI position" after a restart] → Explicitly accepted for Live V1 (see
  Non-Goals and the "trade-cycle-conditional resolver" decision above); not
  a regression introduced by this change — the pre-alignment identity-only
  contract could theoretically have caught this, but the authoritative ABI
  contract does not support that lookup shape at all, so there is no
  alternative implementation of this capability, against the real ABI, that
  would close this gap. Closing it requires the deferred durable-state
  change.
- [A future ABI OpenAPI revision could drift from this change's hand
  -written codec again] → Mitigated by the new authoritative
  cross-repository contract test, which fails on the next drift rather than
  requiring another manual re-discovery.
- [The router's open-trade `entry_bar_open_time_ms` pass-through remains
  unresolved as a real design question] → Explicitly out of scope and
  practically inert today (see "Field propagation" decision above); flagged
  here so it is not mistaken for a decision this change made rather than
  one it deliberately deferred.
- [Tightening `first_fill_at_ms` to strictly-positive could reject a
  legitimate ABI response if ABI ever legitimately reports `0`] → Matches
  the authoritative schema's own `exclusiveMinimum: 0` exactly; if ABI's
  contract changes, the cross-repository contract test surfaces the
  mismatch rather than this codec silently drifting from it.

## Migration Plan

1. Rewrite `runtime/open_position/models.py`, `ports.py`, `errors.py`,
   `resolver.py`; `infrastructure/abi/http_open_position.py`,
   `open_position_codec.py`; and the two-field references in
   `runtime/routing/router.py`, together — these do not compile/type-check
   independently, so they land as one implementation step, not incrementally.
2. Update `tests/contract/abi/test_open_position_client.py`,
   `tests/unit/runtime/test_semantic_pipeline.py`, the production E2E
   fixtures, and add the new authoritative cross-repository contract test.
3. Update `config/runtime.env.example`, `runtime-master-plan.md`,
   `runtime-abi-entry-delivery-map.md` (and generated HTML fragments, if
   they are tracked generated artifacts rather than build output).
4. Remove the empty duplicate change scaffold after re-confirming it is
   still empty and untracked.
5. No data migration: `OpenPositionLookupResponse`/`Request` are transient
   per-call DTOs, never persisted; `StrategyInstanceRuntimeState` and
   `CurrentTradeCycle` are unchanged by this proposal.
6. Rollback: revert the commit(s); no state, ABI, or Engine-side change to
   undo, since ABI's contract is already the authoritative production
   contract independent of this change landing.

## Open Questions

None outstanding for this change's scope. The router's open-trade
`entry_bar_open_time_ms` pass-through semantics (see "Field propagation"
decision) is a real open question but is explicitly deferred, not answered
by guessing, and does not change this change's specs, approach, or task
breakdown — it will need its own design work if and when the open-trade
application operation is built.
