## Context

`abi-execution-event-orchestration` shipped and archived
`AbiExecutionEventOrchestrator.process(event: AbiFirstFillExecutionEvent) ->
StrategyInstanceRuntimeState`: mutex → fresh `get` → fail-closed on missing
state → `apply_first_fill` → conditional `save`. It has no caller in
production code. `create_http_app(...)` (`adapters/http/app.py`) currently
exposes only the MDS-facing closed-bar webhook (`POST
/v1/webhooks/closed-bar`, `BackgroundTasks`-acknowledged) and the two health
endpoints. `build_application` (`bootstrap/application.py`) constructs
exactly one `InMemoryStrategyInstanceRuntimeStateRepository` and one
`StrategyInstanceKeyedMutexRegistry`, passes both into
`StrategyRuntimeOrchestrator`, and never constructs
`AbiExecutionEventOrchestrator`. ABI has no way to deliver a first-fill
fact into a running Runtime process.

This change adds the missing inbound edge and its wiring only. It consumes
`AbiExecutionEventOrchestrator`, `AbiFirstFillExecutionEvent`,
`apply_first_fill`, the repository, and the mutex registry exactly as
already ratified and implemented — no domain logic changes.

## Goals / Non-Goals

**Goals:**

- Define one synchronous HTTP endpoint mapping ABI's first-fill wire fact
  onto `AbiExecutionEventOrchestrator.process(...)`, with a minimal, fixed
  response contract and a fixed typed-exception-to-status mapping.
- Wire `AbiExecutionEventOrchestrator` into `build_application` over the
  same shared repository/mutex-registry instances `StrategyRuntimeOrchestrator`
  already uses, inside the same fail-closed construction boundary.

**Non-Goals:**

- Any ABI-side sender, retry, outbox, or delivery-acknowledgement storage.
- Any change to `AbiFirstFillExecutionEvent`, `AbiExecutionEventOrchestrator`,
  `apply_first_fill`, `align_first_fill_to_entry_bar`,
  `FrozenExecutedEntryContext`, the repository, or the mutex registry.
- Any Engine-facing contract, open-position/open-trade routing, subsequent
  fills, partial-fill lifecycle, or durable Runtime state.
- Any change to the existing closed-bar webhook's route, request/response
  shape, or `BackgroundTasks` semantics.

## Decisions

### The endpoint is synchronous, not `BackgroundTasks`-acknowledged

The closed-bar webhook returns before background work completes because
its caller (MDS) needs only fast acceptance of a fact it will not act on
differently based on Runtime's internal outcome. ABI is different: the
first-fill fact directly gates whether Runtime has a
`FrozenExecutedEntryContext` for that trade cycle, and
`AbiExecutionEventOrchestrator.process(...)` already commits to a strict
sequence — mutex, fresh load, `apply_first_fill`, conditional save — with a
typed exception (`StrategyInstanceStateNotFound`,
`FirstFillInvariantError`) if any step fails. Acknowledging before that
sequence completes would force ABI to treat `200` as "received" rather than
"applied," reintroducing exactly the ambiguity `apply_first_fill`'s
idempotent-retry contract was designed to make unnecessary: a caller that
retries on ambiguous acknowledgement needs the retry to be safe, and safety
here comes from the retry re-running the same synchronous, mutex-serialized
sequence, not from a queue. A synchronous response also lets one fixed HTTP
status carry the orchestrator's own typed outcome (`404`, `409`) directly,
which a fire-and-forget acknowledgement could never do without a second,
separate delivery channel — explicitly out of scope (see Non-Goals in
`abi-execution-event-orchestration`'s own proposal, "the HTTP endpoint ABI
would call... any ABI-side callback sender, delivery retry, outbox").

### `PUT`, not `POST`

The endpoint records one specific fact — "this trade cycle's first fill
happened at this timestamp" — addressed by a URL that already names the
resource (`.../trade-cycles/{trade_cycle_id}/first-fill`), and repeating
the identical request is defined to produce the identical stored outcome
(`apply_first_fill`'s own idempotent-retry contract: "returns the exact
same `state` object reference"). That is `PUT`'s definition — an
idempotent request that establishes a resource's state at an address
identified by the request URL — not `POST`'s (a non-idempotent request to a
collection or process endpoint, which is what the closed-bar webhook
already is: each notification is a new event to process, not a fact
targeting a URL-identified resource). Choosing `PUT` also makes the HTTP
method itself state the endpoint's idempotency, rather than leaving a
reader to infer it only from response-body inspection.

### The path pair (`strategy_instance_id`, `trade_cycle_id`) is the complete binding identity — nothing else belongs there

`AbiExecutionEventOrchestrator.process(...)` needs exactly
`strategy_instance_id` (to key the mutex and the repository lookup) and
`trade_cycle_id` (passed unchanged into `apply_first_fill`, which already
validates it against `current_trade_cycle` and fails closed with
`FirstFillInvariantError` on any mismatch). Both are stable identifiers
that name *which* resource this request addresses — exactly what a URL
path is for — and REST convention already puts identifying path segments
in the path, not the body. No other field participates in addressing the
resource: `first_fill_at_ms` is the fact being recorded *about* that
already-addressed resource, so it belongs in the body, not the path.

### The body carries exactly `first_fill_at_ms` — no Engine-facing, execution-phase, or quantity field

`AbiFirstFillExecutionEvent` (already ratified) carries exactly
`strategy_instance_id`, `trade_cycle_id`, `first_fill_at_ms`, and
explicitly excludes `entry_bar_open_time_ms` and any execution-phase or
quantity field, because that Engine-facing canonical field only exists
*after* `apply_first_fill` normalizes the raw timestamp — it cannot be an
input. With both identifiers already supplied by the path, the only
remaining datum the orchestrator's input needs is the raw fill timestamp
itself, `first_fill_at_ms` — the same name `apply_first_fill` and
`OpenPositionLookupResponse` already use for this exact unnormalized fact.
Any additional field (ticker, timeframe, desired entry, quantity, average
price, order status, fill identifiers, subsequent-fill data) would either
duplicate data Runtime already owns (registered spec, desired entry) or
introduce execution-phase/quantity concepts `apply_first_fill` explicitly
does not model — so the request schema rejects extra fields outright
(`additionalProperties: false`-equivalent strict validation) rather than
silently ignoring them, unlike the closed-bar webhook's deliberately
permissive "ignore additive fields" contract: this endpoint's body has
exactly one field, and a client sending more is a client error, not a
forward-compatible extension.

### The HTTP adapter constructs the event; it never applies the domain transition itself

The adapter's only domain-shaped responsibility is translating validated
HTTP input into `AbiFirstFillExecutionEvent(strategy_instance_id=...,
trade_cycle_id=..., first_fill_at_ms=...)` — a pure data-shape mapping with
no business meaning of its own — and then calling one injected callable.
It must not acquire the mutex, call the repository, or call
`apply_first_fill` directly, because `AbiExecutionEventOrchestrator` already
owns that entire sequence as a single, already-tested unit
(`abi-execution-event-orchestration`, "the orchestrator's constructor
accepts only the shared repository and mutex registry as collaborators");
duplicating any part of that sequence in the HTTP layer would create a
second, untested path to the same mutex and repository, exactly the kind of
duplication `AbiExecutionEventOrchestrator` was designed as the single
sequencing boundary to prevent.

### `200` is returned only after `save` — never before, never via a background task

Because the endpoint is synchronous by design (see above), the FastAPI
handler simply awaits the *result* of the injected callable before
constructing any response: there is no separate "acknowledge, then
process" step to order relative to `save`. The callable itself
(`AbiExecutionEventOrchestrator.process(...)`) does not return until its
own mutex-held sequence — including the conditional `save(...)` — has
completed or raised. A `200` response is therefore only ever constructed
in the success branch reached after that callable returns normally, which
is definitionally after any required save.

### The first successful call and an identical retry return the identical response

`apply_first_fill`'s own idempotency contract (already ratified) guarantees
an identical retry returns the same `state` object with no second save. The
HTTP response contract (`{"status": "first_fill_recorded"}`) carries no
field that could differ between "first application" and "confirmed
no-op retry" — no state, no normalized timestamp, no applied/no-op flag —
so both cases produce byte-identical response bodies from the same success
branch, with no special-casing needed in the adapter to detect which one
occurred. This mirrors the underlying domain contract instead of adding a
second, HTTP-layer notion of "was this new" that `apply_first_fill` was
deliberately designed not to expose.

### An internal alignment `ValueError` is `500`, not `400`

`400` in this contract means "the HTTP request itself was malformed" —
invalid body shape, wrong field type, extra fields, a value failing
`AbiFirstFillExecutionEvent`'s own construction validation. An unsupported
`registered_spec_snapshot.base_timeframe` surfaced as a `ValueError` from
`align_first_fill_to_entry_bar` (invoked inside `apply_first_fill`, which
the orchestrator calls after a request has already been fully validated
and an `AbiFirstFillExecutionEvent` has already been successfully
constructed) is not a fact about the request ABI sent — `base_timeframe`
never appears in the request at all; it comes from Runtime's own
previously registered deployment state. A client cannot fix this error by
sending a different request, which is the operational test for `400` vs
`500`: `400` invites "correct your input and retry"; `500` means "the
server's own state or configuration is at fault." Collapsing this into
`400` would mislead ABI into treating a Runtime-side configuration problem
as a request-shape problem.

### Shared repository/mutex-registry object identity is verified in composition, not in the HTTP or orchestrator layers

`AbiExecutionEventOrchestrator`'s constructor already accepts exactly
`state_repository` and `keyed_mutex_registry` (`abi-execution-event-
orchestration`); it has no way to detect *which* instances it received, nor
should it — that is a composition-root concern. `build_application` is the
one place both `StrategyRuntimeOrchestrator` and
`AbiExecutionEventOrchestrator` are constructed together, so it is the only
place that can pass — and a test can assert — the exact same
`state_repository` and `keyed_mutex_registry` objects into both. This
matches `runtime-production-composition`'s own existing pattern (its
"Exactly one shared state repository and keyed-mutex registry" requirement
already governs `StrategyRuntimeOrchestrator`'s construction the same way);
this change extends that same requirement to cover the new second writer,
rather than inventing a new verification mechanism.

### The closed-bar endpoint is unchanged

`http-closed-bar` already fully specifies MDS's webhook, its
`BackgroundTasks` acknowledgement, and its own error contract; nothing in
this change alters MDS's delivery semantics, the shape of
`CommittedBarEvent`, or `StrategyRuntimeOrchestrator`'s pipeline. The new
first-fill route is added to the same FastAPI app instance purely because
`runtime-production-composition` already commits to "Runtime composes
exactly one production live-entry graph" and one `create_http_app(...)`
call — not because the two endpoints share any behavior. Keeping them
independent routes with independent contracts avoids coupling ABI's
synchronous-acknowledgement need to MDS's fire-and-forget one.

### The ABI-side sender remains a separate, future change

This change defines only Runtime's inbound boundary — what Runtime does
when it receives a valid `PUT`. Nothing here assumes or constrains how ABI
decides to call it, when it retries, or how it recovers from a lost
response; `abi-execution-event-orchestration`'s own proposal already named
"an ABI-side callback sender, delivery retry, outbox" as out of scope, and
this change inherits that boundary rather than reopening it. Building both
sides in one change would also make it impossible to test Runtime's HTTP
contract independently of ABI's delivery strategy, which the test plan
below deliberately keeps decoupled (no real ABI or Strategy Engine server
is started for any test in this change).

### Engine-facing contracts are untouched

`apply_first_fill` already normalizes `first_fill_at_ms` into
`entry_bar_open_time_ms` and freezes it inside `FrozenExecutedEntryContext`
— a Runtime-internal fact that no existing Strategy Engine request or
response shape carries today, and this change adds nothing that would
start carrying it. This change's HTTP response contract deliberately
withholds `entry_bar_open_time_ms` (see the `SUCCESS RESPONSE` boundary
above) precisely so that no Engine-facing surface gains a new field as a
side effect of this change; any future work connecting the frozen entry
context to an Engine-facing contract is a distinct, later decision this
change does not make.

## Risks / Trade-offs

- [A future implementer runs the blocking orchestration call inside `async
  def` directly, blocking the event loop under load] → Mitigated by the
  requirement, recorded in this change's own capability spec, that the
  route be an ordinary synchronous `def` handler (or an equivalent
  guaranteed off-event-loop execution) — not by this design document alone;
  `tasks.md`'s test plan includes an explicit assertion the route is not a
  blocking `async def`.
- [Reusing the same FastAPI app for both endpoints could tempt a future
  change to share validation or error-handling code between them,
  coupling MDS's and ABI's independently evolving contracts] → Accepted:
  this change keeps the two routes' Pydantic models, response models, and
  exception mappings fully separate; no shared base model or shared error
  handler is introduced beyond the two already-independent per-route
  `try`/`except` blocks.
- [`500` for internal alignment errors gives ABI no actionable signal to
  change its own behavior] → Accepted and intentional: an unsupported
  `base_timeframe` is a Runtime deployment-configuration defect, not
  something ABI's request can influence; the fix is operational
  (correcting Runtime's registered spec), not a retry-with-different-input
  loop ABI could execute.

## Migration Plan

Not applicable in this proposal-only pass — no code changes yet. The apply
phase adds one new route to the existing FastAPI app and one new
construction step to `build_application`, both additive; nothing existing
is modified, so migration is a straightforward revert.

## Open Questions

None outstanding for this change's scope. The exact Python identifier for
the new application callable type (e.g. `FirstFillUseCase`) is left to the
apply phase, to be chosen consistent with the existing `BackgroundUseCase`
naming already used in `adapters/http/app.py`.
