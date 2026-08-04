## Context

`first-fill-transition` shipped and archived a pure domain function:

```text
apply_first_fill(state, trade_cycle_id, first_fill_at_ms) -> StrategyInstanceRuntimeState
```

It reads `state.registered_spec_snapshot.base_timeframe`, calls
`align_first_fill_to_entry_bar` to floor the unnormalized fill timestamp
onto the candle grid, and freezes a `FrozenExecutedEntryContext` on
`current_trade_cycle` exactly once — idempotent on an identical retry
(returns the identical input `state` object), fail-closed on a conflicting
retry or a missing/mismatched trade cycle. This function has no caller in
production Runtime code today; it exists only as a tested, ratified pure
transition.

Separately, `StrategyRuntimeOrchestrator` is the one existing top-level
writer over `StrategyInstanceRuntimeStateRepository` and
`StrategyInstanceKeyedMutexRegistry`. It exists to drive the closed-bar
pipeline: `get_or_create` → open-position resolution → use-case routing →
Engine projection → reconciliation → conditional save, all under one held
keyed critical section per `strategy_instance_id`.

ABI observes the entry order's execution on the exchange. At the first
actual fill, ABI captures exactly one raw, unnormalized millisecond
timestamp — the same value `apply_first_fill`'s `first_fill_at_ms`
parameter already exists to receive. That single raw timestamp is the only
fact delivered to Runtime; a repeated delivery is only ever a retry of that
same already-observed fact carrying the identical timestamp, which
`apply_first_fill`'s own idempotency rule already covers ("A repeated
identical first fill is a no-op"). Fills after the first are explicitly out
of scope for this fact: `AbiExecutionEventOrchestrator` is never invoked for
them, their occurrence triggers no renormalization, and they never change an
already-frozen `FrozenExecutedEntryContext`. A different timestamp arriving
after the context is frozen is not "the next fill" — it is a conflict, and
`apply_first_fill` already fails it closed ("A conflicting retried fill
fails closed"). This change designs the handling of exactly one fact per
trade cycle, not a fill stream.

This fact arrives on a path materially different from any closed-bar tick —
asynchronously with respect to it, for a `strategy_instance_id` that
closed-bar processing may be concurrently reading or writing at the same
moment. Applying it requires the same aggregate and the same per-instance
serialization `StrategyRuntimeOrchestrator` already uses — but not
`get_or_create` (the aggregate must already be registered; there is nothing
to "create" from a first-fill event) and not any of
`StrategyRuntimeOrchestrator`'s own pipeline stages (position resolution,
Engine routing, reconciliation are all closed-bar concerns with no meaning
for a first-fill notification).

This change designs that second, narrower top-level writer:
`AbiExecutionEventOrchestrator`. It is deliberately not a rewrite or
extension of `StrategyRuntimeOrchestrator` — the two orchestrators are
peers over shared infrastructure, not a shared class hierarchy or a shared
`process(...)` contract.

## Goals / Non-Goals

**Goals:**

- Define `AbiExecutionEventOrchestrator` as pure sequencing: mutex →
  fresh `get` → fail-closed on missing state → `apply_first_fill` →
  conditional `save`, with no branch of its own logic beyond that sequence.
- Define its application-level input and output precisely enough that a
  later HTTP-adapter change can map ABI's wire payload onto it without
  redesigning this orchestrator.
- Record, as design guidance for a future, separate production-wiring
  change, that this orchestrator and `StrategyRuntimeOrchestrator` must
  share one repository instance and one keyed-mutex registry instance so
  the two writer paths serialize correctly per `strategy_instance_id` — a
  documented note, not a normative requirement of this change's own
  capability spec.
- Keep every timestamp-normalization, candle-boundary, freezing,
  idempotency, and conflict rule exactly where `first-fill-transition`
  already put it — inside `apply_first_fill` — so this change adds zero new
  business logic.

**Non-Goals:**

- The ABI-facing HTTP endpoint, its request/response DTOs, FastAPI route
  registration, or any HTTP error-status mapping. A future change designs
  the wire contract and maps it onto this orchestrator's input; this change
  does not anticipate that mapping's exact shape.
- Production composition (`bootstrap/application.py`, `create_http_app`,
  wiring `AbiExecutionEventOrchestrator` into a running process). This
  change notes, in design.md prose only, the constraint a future wiring
  change must satisfy (shared repository, shared mutex registry); it does
  not encode that constraint as a normative capability requirement, and
  does not implement or test the wiring itself.
- Any new timestamp-normalization rule, state machine, command builder,
  generic execution-event dispatcher, event-handler registry, application
  port wrapping `apply_first_fill`, or abstraction over the conditional-save
  pattern already used by `StrategyRuntimeOrchestrator`. This orchestrator
  is one small, concrete sequence, not a framework.
- Any subsequent-fill, partial-fill, quantity, average-price, or execution-
  phase concept. `apply_first_fill` already commits to introducing none of
  these ("apply_first_fill introduces no execution-phase or quantity
  lifecycle"); this orchestrator inherits that boundary unchanged.
  `AbiExecutionEventOrchestrator` is designed to receive exactly one raw
  first-fill timestamp per trade cycle (plus idempotent retries of that same
  timestamp); it is never invoked for a fill after the first, and this
  change does not design what would call it for one.
- Modifying `StrategyRuntimeOrchestrator`, `EntryReconciliationOrchestrator`,
  the repository, the mutex registry, or `apply_first_fill` themselves. All
  four are consumed as already-ratified, unmodified capabilities.

## Decisions

### The orchestrator's input reuses `first_fill_at_ms`, not a new name

The task instructions require choosing the input timestamp field's exact
name only after checking existing models and specs, and forbid using the
Engine-facing name `entry_bar_open_time_ms` at this layer (that name is
created by `apply_first_fill`'s internal call to
`align_first_fill_to_entry_bar`; it does not exist before the domain
transition runs). Checking both existing sources settles this without
inventing anything:

- `apply_first_fill(state, trade_cycle_id, first_fill_at_ms)` — the domain
  transition's own third parameter is already named `first_fill_at_ms`.
- `OpenPositionLookupResponse.first_fill_at_ms` (`abi-open-position-lookup-
  client`, already ratified) — ABI's own open-position contract already
  reports this exact execution fact under this exact field name, as "a
  strictly positive integer" fill timestamp, with the accompanying
  capability text explicitly framing it as an "ABI/Runtime execution fact"
  that must not reach any Strategy Engine field.

`AbiExecutionEventOrchestrator`'s typed input therefore carries
`strategy_instance_id: str`, `trade_cycle_id: str`, and
`first_fill_at_ms: int` — the same name, the same meaning, the same
unnormalized-timestamp semantics already established on both sides of this
orchestrator (the domain transition it calls, and the ABI contract this
event ultimately originates from). No new vocabulary is introduced.

**Alternative considered — a name like `execution_timestamp_ms` or
`raw_fill_timestamp_ms`.** Rejected: it would create a second name for the
identical value `apply_first_fill` already calls `first_fill_at_ms`, forcing
a pointless rename at the call site and inviting future confusion about
whether the two names denote the same fact.

### `AbiExecutionEventOrchestrator` is a sibling, not a subclass or a shared base with `StrategyRuntimeOrchestrator`

Both orchestrators hold the same keyed mutex and use the same repository
contract, but their pipelines share no steps: `StrategyRuntimeOrchestrator`
runs `get_or_create` → position resolution → routing → Engine projection →
reconciliation; `AbiExecutionEventOrchestrator` runs `get` → one domain-
transition call. Forcing a shared base class or a shared `process(...)`
signature over two pipelines this different would either leak closed-bar-
only concepts (position resolution, Engine projection) into the ABI path,
or force `StrategyRuntimeOrchestrator` to accommodate a `get`-not-`get_or_
create` load it does not need. `AbiExecutionEventOrchestrator` is instead a
plain, independent class constructed with the same two shared collaborators
(`state_repository`, `keyed_mutex_registry`) plus nothing else — no
open-position resolver, no use-case router, no Engine port, no reconciliation
orchestrator, because it calls none of them.

**Alternative considered — extend `StrategyRuntimeOrchestrator` with a
second entry method for ABI events.** Rejected: `StrategyRuntimeOrchestrator`
already documents that it "owns the complete keyed closed-bar critical
section" as its single, closed responsibility; adding a second, unrelated
entry point would blur that boundary and expand its constructor with
collaborators the ABI path never touches.

### `get`, never `get_or_create` — and fail closed, don't synthesize

`StrategyRuntimeOrchestrator` uses `get_or_create` because a closed-bar tick
for a brand-new `strategy_instance_id` is exactly when Runtime first learns
that instance exists — creating the aggregate is correct there.
`AbiExecutionEventOrchestrator` never legitimately encounters a genuinely
new instance: ABI can only report a fill for a trade cycle that Runtime
itself created (via `StrategyRuntimeOrchestrator`'s own reconciliation path)
and sent to ABI as an entry package in the first place. If
`state_repository.get(strategy_instance_id)` returns `None` here, that is
not "first contact" — it is a genuine invariant violation (ABI reporting a
fill for an instance Runtime has no record of, or a lost/reset in-memory
repository), and the orchestrator fails closed rather than silently
registering a bare aggregate `apply_first_fill` could never legitimately
freeze against (it requires an existing `current_trade_cycle`, which a
synthesized empty aggregate would not have either).

Reusing `StrategyInstanceStateNotFound` for this failure (rather than
inventing a new exception) is intentional per the task's own instruction to
prefer reuse when semantics already match: the existing exception already
means exactly "no aggregate is registered under this
`strategy_instance_id`" (it is raised by `save(...)` for an unregistered
identity today); `get(...)` returning `None` is the same fact observed one
step earlier in the same pipeline. A future HTTP-mapping change decides how
this exception becomes a wire error; this change does not.

**Alternative considered — call `get_or_create` and rely on `apply_first_
fill` to fail closed on the resulting aggregate's missing `current_trade_
cycle`.** Rejected: this would silently register a bare aggregate with no
`strategy_id`, `registered_spec_snapshot`, or risk data the caller can
supply (the ABI event carries none of that), corrupting the repository with
a malformed record before `apply_first_fill` ever runs, purely to reach the
same fail-closed outcome one call later and worse.

### Conditional save uses identity (`is`), matching `apply_first_fill`'s own documented contract — deliberately unlike `StrategyRuntimeOrchestrator`'s value-equality rule

`strategy-runtime-orchestrator` explicitly requires value equality
(`==`) for its own no-op test, and explicitly forbids `is` as "the
orchestrator does not use `resulting_state is not source_state` as a change
test" — because its nested `EntryReconciliationOrchestrator.execute(...)`
may legitimately return a new, value-equal Python object for a logical
no-op.

`apply_first_fill` is different by its own ratified contract: "A repeated
identical first fill is a no-op... `apply_first_fill` SHALL return the
identical input `state` object, unmodified" (`first-fill-transition`,
Scenario "The same fill retried is a no-op" — "returns the exact same
`state` object reference"). Object identity is not an incidental
implementation detail of `apply_first_fill` here; it is the contract. Using
`resulting_state is state` in `AbiExecutionEventOrchestrator` therefore
matches the domain transition it wraps exactly, and using `==` instead would
be a weaker, non-equivalent check that happens to agree with `is` in every
case `apply_first_fill` can actually produce — so `is` is both correct and
the more precise statement of what the transition guarantees.

**Alternative considered — use `==` uniformly across both orchestrators for
consistency.** Rejected: consistency with `StrategyRuntimeOrchestrator`
would be cosmetic, not substantive, since the two orchestrators wrap
differently-contracted operations; matching each orchestrator's save
condition to the actual contract of the operation it wraps is more precise
than a uniform rule that happens to work for both today.

### Shared repository and shared mutex registry: a noted constraint for a future, separate wiring change — not designed or tested here

`strategy-instance-keyed-coordination` already commits to "Share one
registry across later writers": "When later Runtime state writers receive
the same registry instance and request the same strategy-instance key, both
critical sections are backed by the same keyed lock." `AbiExecutionEventOrchestrator`
is exactly the "later writer" that requirement was written to anticipate.
Without a future production wiring passing one shared
`StrategyInstanceRuntimeStateRepository` instance and one shared
`StrategyInstanceKeyedMutexRegistry` instance to both
`AbiExecutionEventOrchestrator` and `StrategyRuntimeOrchestrator`, two
separately-constructed repository or registry instances would silently
defeat serialization between the two writer paths — the closed-bar writer
could save a new `CurrentTradeCycle` while a first-fill event is mid-flight
against a stale snapshot, or vice versa.

This change records that constraint here, in design.md, as guidance for
whichever future, separate production-composition change wires both
orchestrators together. It is deliberately **not** encoded as a normative
requirement in this change's own capability spec, and this change neither
implements nor tests it: `AbiExecutionEventOrchestrator` is constructed here
with exactly the two collaborators
(`state_repository`, `keyed_mutex_registry`) its own sequencing needs
(design.md, "Decisions"; `specs/abi-execution-event-orchestration/spec.md`);
how a future composition root supplies those two collaborators to both
orchestrators, and proves they are the same instances, belongs entirely to
that later, separate wiring change.

**Alternative considered — let each writer own its own repository/registry
pair and reconcile through some other mechanism (e.g., a database-level
lock once a durable repository exists).** Rejected as out of scope and
unnecessary: Live V1's repository and mutex registry are explicitly
in-process, non-durable capabilities (`strategy-instance-keyed-coordination`,
"Live V1 coordination makes no cross-process guarantee"); within one
process, sharing the same two objects is sufficient and is exactly what
both existing capabilities were designed to support.

## Risks / Trade-offs

- [A future production-wiring change forgets to share the repository/mutex-
  registry instances between the two orchestrators, silently reintroducing
  a race] → Not mitigated by this change beyond stating the constraint in
  prose above: this change intentionally leaves the shared-instance
  guarantee unencoded and untested, since designing and testing production
  wiring is explicitly out of scope here (see Non-Goals). The future wiring
  change is responsible for both satisfying and proving this constraint.
- [Reusing `StrategyInstanceStateNotFound` broadens its call sites from one
  (`save` on an unregistered identity) to two, slightly widening what
  "instance state not found" can mean operationally] → Accepted: both call
  sites report the identical underlying fact (no aggregate registered under
  this `strategy_instance_id`); a future HTTP-mapping change can still
  distinguish them by call site if that ever becomes operationally useful,
  without this change needing to pre-guess that need.
- [This design fixes the input field name and shape without also fixing how
  a future HTTP DTO maps onto it, so a later change could still choose an
  incompatible wire shape] → Accepted and intentional: mapping ABI's wire
  payload onto this orchestrator's typed input is explicitly deferred to
  the HTTP-adapter change named in Non-Goals; this design only needs the
  application-level input to be stable and precisely named, which it is.

## Migration Plan

Not applicable in this proposal-only pass — no code changes, so there is
nothing to deploy or roll back yet. The apply phase of this change will add
the `AbiExecutionEventOrchestrator` class and its typed input/output models
as new, additive modules with no modification to any existing production
file; migration is a straightforward revert, since nothing existing is
touched.

## Open Questions

None outstanding for this change's scope. Where exactly the new module
lives inside `runtime/` (e.g. alongside `runtime/first_fill/` versus a new
`runtime/abi_execution_event/` package) is left to this change's own apply
phase, since it has no bearing on this design's sequencing contract, input
shape, or shared-infrastructure constraint.
