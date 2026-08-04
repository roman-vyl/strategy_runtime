## Why

`abi-execution-event-orchestration` (archived
`2026-08-04-runtime-abi-execution-event-orchestration-v1`) shipped
`AbiExecutionEventOrchestrator.process(event: AbiFirstFillExecutionEvent) ->
StrategyInstanceRuntimeState`: a second top-level writer path, sharing
`StrategyRuntimeOrchestrator`'s `StrategyInstanceRuntimeStateRepository`
and `StrategyInstanceKeyedMutexRegistry`, that acquires the keyed mutex,
loads fresh state, calls the existing `apply_first_fill` domain transition,
and conditionally saves. Nothing calls it yet: it has no HTTP ingress, and
`bootstrap/application.py` never constructs it. ABI has no way to deliver a
first-fill fact to Runtime in production.

This change adds exactly that missing edge: an inbound HTTP endpoint ABI
calls, and the production wiring connecting it to the already-shipped
orchestrator through the same shared repository and mutex registry
`StrategyRuntimeOrchestrator` already uses. It introduces no new domain
logic — `apply_first_fill`, `align_first_fill_to_entry_bar`,
`FrozenExecutedEntryContext`, the repository, and the mutex registry are
all consumed unmodified, exactly as `abi-execution-event-orchestration`
already committed to.

## What Changes

- Add a new capability, `http-abi-first-fill`, defining a synchronous
  `PUT /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill`
  endpoint: identifiers travel only in the path; the body carries exactly
  one field, `first_fill_at_ms` (strict positive integer, no `bool`, no
  `float`, no extra fields); the handler builds an
  `AbiFirstFillExecutionEvent` from validated path and body input, calls a
  single injected application callable synchronously, and returns `HTTP
  200 {"status":"first_fill_recorded"}` only after that callable — and
  therefore mutex acquisition, fresh load, `apply_first_fill`, and any
  required save — has fully completed. First application and an identical
  retry return the identical response; no Runtime state, timestamp, or
  applied/no-op distinction is ever exposed. Known typed exceptions map to
  fixed HTTP statuses: `StrategyInstanceStateNotFound` to `404`,
  `FirstFillInvariantError` to `409`, not-ready to `503`; every other
  exception — including a `ValueError` propagating from internal alignment
  after a structurally valid request — maps to `500`, never `400`. This
  capability extends `create_http_app(...)` with one new route and one new
  optional callable parameter; it does not replace or duplicate the
  existing `http-closed-bar` capability, whose webhook, background-task
  acknowledgement, and health endpoints are unchanged.
- Modify `runtime-production-composition` to construct exactly one
  `AbiExecutionEventOrchestrator`, passing it the same `state_repository`
  and `keyed_mutex_registry` instances `StrategyRuntimeOrchestrator`
  already receives (no second repository, no second mutex registry), wrap
  its `.process(...)` in a thin callable, and pass that callable into
  `create_http_app(...)` as the new first-fill application port. A ready
  application gets a connected callable; a not-ready application gets
  `None` and never executes the first-fill use case. This wiring introduces
  no new outbound HTTP client, no new lifecycle owner, and no new
  environment variable — it reuses the composition root's existing
  fail-closed rollback semantics for any construction failure in this new,
  now-mandatory wiring step.

## Capabilities

### New Capabilities

- `http-abi-first-fill`: The synchronous inbound HTTP boundary ABI calls to
  report a trade cycle's first fill, validating the wire contract, building
  `AbiFirstFillExecutionEvent`, and mapping the already-shipped
  `AbiExecutionEventOrchestrator`'s typed outcomes to a minimal, fixed HTTP
  response contract.

### Modified Capabilities

- `runtime-production-composition`: Gains the construction of exactly one
  `AbiExecutionEventOrchestrator` over the same shared
  `state_repository`/`keyed_mutex_registry` instances
  `StrategyRuntimeOrchestrator` already uses, and gains passing a thin
  `process_first_fill` callable into `create_http_app(...)`. No existing
  requirement of this capability (single repository/registry instance,
  outbound-client lifecycle ownership, fail-closed configuration gating) is
  weakened; this change only adds one more mandatory construction step
  inside the same fail-closed boundary.

`abi-execution-event-orchestration` and `first-fill-transition` are
consumed exactly as already specified and ratified; neither capability's
requirements change. This change is ingress-and-wiring only.

## Impact

- New HTTP route surface: one `PUT` endpoint added to the existing FastAPI
  app via `create_http_app(...)`; the existing `POST
  /v1/webhooks/closed-bar` route, its `BackgroundTasks` semantics, and the
  two health endpoints are unchanged.
- New production wiring inside `bootstrap/application.py`:
  `AbiExecutionEventOrchestrator` constructed once, using the same shared
  repository and mutex-registry instances; one new thin callable passed
  into `create_http_app(...)`. No new outbound HTTP client, no new
  environment variable, no new startup mode, no alternative production
  composition path.
- No change to `AbiFirstFillExecutionEvent`, `AbiExecutionEventOrchestrator`,
  `apply_first_fill`, `align_first_fill_to_entry_bar`,
  `FrozenExecutedEntryContext`, the repository implementation, or the mutex
  implementation.
- Explicitly out of scope: any ABI-side HTTP sender, ABI callback retry,
  ABI outbox, ABI execution observation, private WebSocket, polling,
  delivery-acknowledgement storage, durable deduplication, Strategy Engine
  request/response changes, open-position/open-trade routing, subsequent
  fills, partial-fill lifecycle, filled/remaining quantity, average
  execution price, a fill ledger, a durable Runtime repository, restart
  recovery, or MDS changes. Named explicitly so a future reader does not
  infer they were considered and rejected here — they were simply not
  addressed by this proposal-only pass.
