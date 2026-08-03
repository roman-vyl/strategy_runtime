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
  derives one timestamp from another. This change does not decide, and does
  not implement, any mapping of `first_fill_at_ms`/`average_entry_price`
  into a Strategy Engine request field — see "position_open=true fails
  closed before Engine, with no field mapping" below.
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

### position_open=true fails closed before Engine, with no field mapping

An earlier draft of this design propagated the `first_fill_at_ms` rename
straight through into `OpenTradeProjectionRequest.entry_bar_open_time_ms` —
Engine's existing open-trade wire field — as a "same-value pass-through,
not a new computation." On review, that framing does not hold: whatever the
right relationship between an exchange fill timestamp and Engine's
candle-boundary-shaped `entry_bar_open_time_ms` field turns out to be, this
change has no basis for asserting today's identity mapping is it. Passing
the renamed value through silently would make an implicit field-mapping
decision by omission — exactly the kind of undesigned Engine-contract
question this change explicitly defers (see Non-Goals).

Instead, `position_open=true` now fails closed **before** any Engine call:

```text
resolved.position_open?
  false -> unchanged: build LiveEntryProjectionRequest, call
           StrategyEngineLiveEntryPort.project_live_entry(...)
  true  -> raise OpenTradeContextUnavailable(unit.strategy_instance_id)
           immediately -- no OpenTradeProjectionRequest is constructed,
           no StrategyEngineOpenTradePort call is made, no
           first_fill_at_ms/average_entry_price value is read for this
           purpose at all
```

`OpenTradeContextUnavailable` — the router's own existing exception,
already raised (pre-alignment) when open-trade context looked incomplete —
is reused rather than introducing a new exception type, per this change's
instruction to fix a temporary boundary with an existing typed failure.
Reusing it does broaden its practical meaning: previously it meant "the
locally available facts are incomplete"; now it also covers "the facts are
available, but this change has not designed how they may safely reach
Engine." Both are, at the call site, the same observable outcome (open-trade
projection cannot proceed), so the broadening is judged acceptable rather
than worth a second exception type for a temporary state. It stays in
`runtime/routing/errors.py` (the router's own error module) rather than
reusing the orchestrator-layer `OpenTradeProjectionUnsupportedError`, which
would require routing to import from orchestrator — a layering direction
the codebase does not otherwise have — and which is raised for a materially
different condition (a fully-formed `OpenTradeProjectedStrategyInstance`
that reached the orchestrator, not a routing-time refusal to build one).

**Consequence: `OpenTradeProjectedStrategyInstance` becomes unreachable from
production routing in this change.** `StrategyUseCaseRouter.route(...)` is
the only production constructor of that type; once it always raises before
reaching that construction for `position_open=true`,
`OpenTradeProjectionUnsupportedError` (raised by
`StrategyRuntimeOrchestrator` for that type) has no live call path left
through the router. It remains reachable only where a test constructs
`OpenTradeProjectedStrategyInstance` directly to exercise the orchestrator's
typed-branch dispatch in isolation (as `test_semantic_pipeline.py` and the
orchestrator's own focused tests already do) — that isolation testing is
unaffected by this change and is not something this change removes.

**Propagation is unchanged.** `OpenTradeContextUnavailable` raised inside
`StrategyUseCaseRouter.route(...)`, itself called from
`StrategyRuntimeOrchestrator.process(...)` inside the held keyed critical
section, already propagates uncaught to `CommittedBarOrchestrator`'s
existing per-unit failure handling under the current, unmodified
"Propagate Engine projection failure" requirement in the
`strategy-runtime-orchestrator` spec. No new error-propagation behavior is
introduced by this decision.

**Alternative considered — still call Engine open-trade, omitting only the
disputed field.** Rejected: `OpenTradeProjectionRequest.entry_bar_open_time_ms`
is a required field with no defined "absent" representation; omitting it is
not expressible without changing the Engine port model, which is out of
scope.

**Alternative considered — introduce a new, precisely-named exception for
this specific temporary state.** Rejected for now as premature naming for a
boundary explicitly expected to be revisited once Engine field-mapping is
designed; reusing `OpenTradeContextUnavailable` costs nothing observable at
the current single call site and avoids naming something that may need to
change shape once the real design lands.

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
- [Open-trade routing now fails closed unconditionally for
  `position_open=true`, even once a real trade cycle and real fill facts
  exist] → Accepted and temporary by design (see "position_open=true fails
  closed before Engine" above): this change has no basis for deciding how
  `first_fill_at_ms`/`average_entry_price` should reach Engine, and passing
  them through unexamined would be a worse outcome than an explicit,
  visible fail-closed boundary. `OpenTradeContextUnavailable` already
  propagates to a journaled failed-dispatch outcome (unchanged), so this is
  observable, not silent.
- [Tightening `first_fill_at_ms` to strictly-positive could reject a
  legitimate ABI response if ABI ever legitimately reports `0`] → Matches
  the authoritative schema's own `exclusiveMinimum: 0` exactly; if ABI's
  contract changes, the cross-repository contract test surfaces the
  mismatch rather than this codec silently drifting from it.

## Migration Plan

1. Rewrite `runtime/open_position/models.py`, `ports.py`, `errors.py`,
   `resolver.py`; `infrastructure/abi/http_open_position.py`,
   `open_position_codec.py`; and `runtime/routing/router.py`'s open-trade
   branch (remove request construction and the Engine call; raise
   `OpenTradeContextUnavailable` unconditionally for `position_open=true`),
   together — these do not compile/type-check independently, so they land
   as one implementation step, not incrementally.
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

None outstanding for this change's scope. How, or whether,
`first_fill_at_ms`/`average_entry_price` should ever reach Strategy Engine
is a real open question, but this change answers what to do about it *now*
(fail closed before Engine, map nothing) rather than leaving that behavior
undecided — the further question of Engine's eventual contract is out of
scope by design (see Non-Goals), not an unresolved unknown inside this
change's own approach, and does not change this change's specs, decisions,
or task breakdown. It will need its own design work if and when the
open-trade application operation is built.
