## 1. Request/Response Models

- [x] 1.1 Add a `FirstFillRequest` Pydantic model (or equivalent naming
  consistent with `adapters/http/models.py`'s existing `ClosedBarRequest`)
  carrying exactly `first_fill_at_ms: StrictInt` with `strict=True` and
  `extra="forbid"` (unlike `ClosedBarRequest`'s `extra="ignore"` — this
  endpoint rejects additive fields per `specs/http-abi-first-fill/spec.md`),
  plus a validator rejecting zero/negative values. `StrictInt` already
  rejects `bool` and `float` under `strict=True`, consistent with the
  existing `open_time_ms` field's pattern.
- [x] 1.2 Add fixed response models: a `first_fill_recorded` success model,
  a `strategy_instance_state_not_found` model, a `first_fill_conflict`
  model, and reuse the existing `NotReadyResponse` for `503` and a new
  `internal_error` model for `500`. Reuse `RejectedResponse`
  (`{"status":"rejected","reason":"invalid_webhook"}`) for `400` — it
  already matches this endpoint's required `400` body exactly.

## 2. HTTP Adapter Route

- [x] 2.1 Extend `create_http_app(...)` (`adapters/http/app.py`) with a new
  **required, keyword-only** parameter for the first-fill application
  callable — `process_first_fill: FirstFillUseCase | None` (no default
  value), name the type alias per existing convention (e.g.
  `FirstFillUseCase = Callable[[AbiFirstFillExecutionEvent],
  StrategyInstanceRuntimeState]`, mirroring the existing `BackgroundUseCase`
  type alias) — and store it on `app.state` alongside
  `process_committed_bar`. No default means every caller of
  `create_http_app(...)`, in production wiring and in every test, must
  explicitly pass either a connected callable or `None` — no caller can
  silently build an app without making that decision.
- [x] 2.2 Add `PUT
  /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill`
  as an ordinary synchronous `def` route (not `async def`) so FastAPI runs
  it in its worker threadpool, keeping the blocking mutex/repository
  sequence off the event loop without a new concurrency primitive.
- [x] 2.3 Route body: check `app.state.ready` and
  `app.state.process_first_fill is not None`, returning `503`
  `NotReadyResponse` immediately if either is false, before constructing
  any event. Otherwise construct `AbiFirstFillExecutionEvent(
  strategy_instance_id=<path>, trade_cycle_id=<path>,
  first_fill_at_ms=<validated body>)`, call
  `app.state.process_first_fill(event)` exactly once, and return `200`
  `{"status": "first_fill_recorded"}` only after that call returns.
- [x] 2.4 Map exceptions raised by the callable to fixed responses:
  `StrategyInstanceStateNotFound` to `404`
  `{"status":"strategy_instance_state_not_found"}`;
  `FirstFillInvariantError` (and the `ValueError` it lets propagate
  unwrapped from `align_first_fill_to_entry_bar`, since both surface as
  exceptions from the same callable) — note `FirstFillInvariantError`
  maps to `409`, while any other exception including that internal
  `ValueError` maps to `500`, distinguished by exact exception type, not
  by message content; `AbiFirstFillExecutionEvent` construction failure
  (invalid path segment) to `400` `RejectedResponse`; any other exception
  to `500` `{"status":"internal_error"}`, logged via `app.state.logger`
  without including the exception message or a stack trace in the response
  body.
- [x] 2.5 Register a `RequestValidationError`-driven `400` for body
  validation failures the same way the existing closed-bar route relies on
  `create_http_app`'s existing `validation_error_handler` — confirm this
  shared handler already produces the required
  `{"status":"rejected","reason":"invalid_webhook"}` body for this new
  route's Pydantic validation failures (missing field, wrong type, extra
  field with `extra="forbid"`) with no new exception handler needed.
- [x] 2.6 Do not add any mutex acquisition, repository call,
  `apply_first_fill` call, save decision, timestamp normalization, or
  Strategy Engine/ABI DTO construction inside the route itself — the route
  calls only the injected callable and translates its outcome.

## 3. Production Composition

- [x] 3.1 In `build_application` (`bootstrap/application.py`), after
  `state_repository` and `keyed_mutex_registry` are constructed (same
  location `StrategyRuntimeOrchestrator` already receives them), construct
  exactly one `AbiExecutionEventOrchestrator(state_repository=
  state_repository, keyed_mutex_registry=keyed_mutex_registry)` — the exact
  same two objects, not new ones.
- [x] 3.2 Define a thin `process_first_fill(event: AbiFirstFillExecutionEvent)
  -> StrategyInstanceRuntimeState` closure that calls
  `abi_execution_event_orchestrator.process(event)` and returns its result
  unmodified — mirroring the existing `process_committed_bar` closure's
  shape.
- [x] 3.3 Pass `process_first_fill=process_first_fill` explicitly into
  `create_http_app(...)`'s new required parameter on the ready-application
  construction path; the not-ready fallback path (`except Exception:`
  branch) explicitly passes `process_first_fill=None`, matching its
  existing explicit `process_committed_bar=None` call — both branches must
  pass the parameter by name since it has no default.
- [x] 3.4 Do not add a new environment variable, new outbound HTTP client,
  new lifecycle owner, or new startup mode for this wiring; any failure
  constructing `AbiExecutionEventOrchestrator` or connecting its callable
  is caught by the same existing `try`/`except Exception` boundary already
  wrapping the rest of `build_application`, triggering the same
  `lifecycle.close_all_once()` rollback and not-ready fallback already in
  place.

## 4. HTTP Contract Tests

- [x] 4.1 The route method is exactly `PUT`.
- [x] 4.2 The route path is exactly `/v1/strategy-instances/
  {strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill`.
- [x] 4.3 A valid body contains only `first_fill_at_ms`; `strategy_instance_id`
  and `trade_cycle_id` in the body (duplicating the path) are rejected as
  extra fields.
- [x] 4.4 First successful call returns `200
  {"status":"first_fill_recorded"}`.
- [x] 4.5 An identical retry (same path, same `first_fill_at_ms`) returns
  the identical `200 {"status":"first_fill_recorded"}` response.
- [x] 4.6 The HTTP response is only returned after the injected application
  callable (a test double standing in for
  `AbiExecutionEventOrchestrator.process`) has returned — assert via a
  callable that records an ordering marker before returning, and assert
  the marker is set before the response is received by the test client.
- [x] 4.7 `BackgroundTasks` is not used for this route — assert no
  background task is registered during a first-fill request (e.g. via a
  spy/patch on `BackgroundTasks.add_task`, or by asserting the route
  signature has no `BackgroundTasks` parameter).
- [x] 4.8 Each of `bool`, `float`, `string`, zero, negative, missing, and
  extra-field `first_fill_at_ms` (and any other extra top-level field)
  independently produces `400 {"status":"rejected","reason":
  "invalid_webhook"}`.
- [x] 4.9 A callable raising `StrategyInstanceStateNotFound` produces `404
  {"status":"strategy_instance_state_not_found"}`.
- [x] 4.10 A callable raising `FirstFillInvariantError` produces `409
  {"status":"first_fill_conflict"}`.
- [x] 4.11 A not-ready application (`ready=False` or
  `process_first_fill=None`) produces `503 {"status":"not_ready"}` without
  invoking any callable.
- [x] 4.12 A callable raising an unexpected exception (e.g. a bare
  `RuntimeError` standing in for a repository failure) produces `500
  {"status":"internal_error"}`.
- [x] 4.13 A callable raising a bare `ValueError` (standing in for
  `align_first_fill_to_entry_bar`'s unwrapped alignment failure) produces
  `500`, not `400` — a dedicated test distinct from 4.8's request-shape
  `400` cases, proving the distinction is made by exception type after
  event construction, not by request content.
- [x] 4.14 The `200` response body contains no `state`, no normalized
  timestamp, and no field distinguishing a new application from a
  confirmed no-op — assert the response body equals exactly
  `{"status":"first_fill_recorded"}` for both a first call and a retry.
- [x] 4.15 The existing closed-bar endpoint's contract (method, path,
  request/response shape, `BackgroundTasks` registration, `400`/`503`/`500`
  responses) is unchanged — rerun (or reference) its existing test
  coverage to confirm no regression from the new route or the new
  `create_http_app(...)` parameter.
- [x] 4.16 A normal, Unicode-containing, whitespace-containing, and
  literal-`%`-containing `strategy_instance_id` (and independently
  `trade_cycle_id`), each properly percent-encoded by the test client,
  round-trips byte-for-byte into the `AbiFirstFillExecutionEvent` the
  capturing application callable receives — four cases minimum, per
  `specs/http-abi-first-fill/spec.md`'s path-identifier scenarios.
- [x] 4.17 A missing `Content-Type` header and an incorrect `Content-Type`
  (e.g. `text/plain`) each independently produce `400
  {"status":"rejected","reason":"invalid_webhook"}`, not `415`.
- [x] 4.18 An `Accept` header that does not include `application/json`
  does not change the response status (no `406`) — confirm the response
  is governed only by body/path validation.

## Note on out-of-scope routing cases

A literal `/` inside `strategy_instance_id` or `trade_cycle_id` cannot be
addressed by this endpoint's routing under any encoding (see
`specs/http-abi-first-fill/spec.md`, "A slash-containing identifier is not
addressable by this endpoint") — no test asserts a specific response for
this case, since it is a routing-boundary limitation, not a validated
input. A dot-only (`.` or `..`) segment has no guaranteed contract at this
boundary (client-side URL normalization may collapse it before the request
is ever sent) — no test asserts either "supported" or "rejected with a
typed error" for this case; this change does not build a custom router to
give it one.

## 5. HTTP Adapter Boundary Tests

- [x] 5.1 Given a valid path/body pair, the adapter constructs exactly one
  `AbiFirstFillExecutionEvent` with `strategy_instance_id` and
  `trade_cycle_id` from the path and `first_fill_at_ms` from the body,
  unmodified — assert via a capturing test double for the application
  callable.
- [x] 5.2 The adapter calls the injected application callable exactly once
  per request, never zero and never more than once, including on a request
  that ultimately errors after the callable is invoked.
- [x] 5.3 The adapter never touches the repository or mutex registry
  directly and never calls `apply_first_fill` directly. `create_http_app`
  accepts no repository or mutex-registry parameter — this is a structural
  property, not something a wired fake could prove, since
  `adapters/http/app.py` has no such collaborator to receive one in the
  first place. Prove it by: (a) a static/import-level check that
  `adapters/http/app.py` does not import
  `StrategyInstanceRuntimeStateRepository`,
  `StrategyInstanceKeyedMutexRegistry`, or `apply_first_fill` (e.g. via an
  AST or source-grep architecture-guardrail test, matching the pattern
  already used for `abi-execution-event-orchestration`'s own architecture
  guardrail tests); and (b) the capturing-callable proof from 5.1/5.2 as
  the main behavioral evidence — the adapter's only route to Runtime state
  is the one injected `process_first_fill` callable it calls exactly once.
  Do not add a repository or mutex-registry parameter to `create_http_app`
  to make this testable a different way.
- [x] 5.4 Each known exception type (`StrategyInstanceStateNotFound`,
  `FirstFillInvariantError`) raised by a stub callable produces its exact
  documented typed HTTP response (404, 409 respectively) with no other
  status possible.
- [x] 5.5 An unknown exception raised by a stub callable is logged via
  `app.state.logger` (assert a log call occurred) and produces exactly
  `500 {"status":"internal_error"}`.

## 6. Composition Tests

- [x] 6.1 `AbiExecutionEventOrchestrator` is constructed exactly once by
  `build_application` for a `ready=True` result (assert via a constructor
  spy or by asserting exactly one instance is reachable from the returned
  app's collaborators).
- [x] 6.2 The constructed `AbiExecutionEventOrchestrator` receives the
  exact production `state_repository` object — assert object identity
  (`is`), not equality, against `app.state.state_repository`.
- [x] 6.3 The constructed `AbiExecutionEventOrchestrator` receives the
  exact production `keyed_mutex_registry` object — assert object identity
  against `app.state.keyed_mutex_registry`.
- [x] 6.4 `StrategyRuntimeOrchestrator` and `AbiExecutionEventOrchestrator`
  receive the exact same `state_repository` and `keyed_mutex_registry`
  objects as each other (cross-orchestrator identity assertion, not just
  each against `app.state` independently).
- [x] 6.5 A `ready=True` application's `app.state.process_first_fill` (or
  equivalent attribute) is a connected, non-`None` callable that invokes
  `AbiExecutionEventOrchestrator.process`.
- [x] 6.6 A `ready=False` application never executes the first-fill use
  case: `app.state.process_first_fill` is `None`, and a `PUT` first-fill
  request against a not-ready app returns `503` without constructing an
  event or calling any orchestrator.
- [x] 6.7 The new wiring adds zero outbound HTTP clients — assert
  `len(app.state.outbound_http_clients) == 4` (unchanged from before this
  change) for a ready application.
- [x] 6.8 The existing outbound-client lifecycle (construct-once,
  close-once-on-shutdown, close-on-rollback) is unchanged — rerun (or
  reference) existing lifecycle tests to confirm no regression.
- [x] 6.9 A forced failure in constructing `AbiExecutionEventOrchestrator`
  or connecting its callable (e.g. monkeypatching the constructor to raise)
  causes `build_application` to return `ready=False`, with every
  already-constructed outbound HTTP client closed exactly once via startup
  rollback, and no partially wired `ready=True` application returned.

## 7. Vertical Runtime Test

- [x] 7.1 Seed a shared `InMemoryStrategyInstanceRuntimeStateRepository`
  with a `StrategyInstanceRuntimeState` carrying a `current_trade_cycle`
  (via the same fixture pattern already used by
  `abi-execution-event-orchestration`'s own integration test, task 3.11 in
  its archived `tasks.md`).
- [x] 7.2 Wire that repository and a real
  `StrategyInstanceKeyedMutexRegistry` through a real
  `AbiExecutionEventOrchestrator` into a test-constructed `create_http_app`
  (bypassing full `build_application`, since Strategy Engine/ABI outbound
  clients are irrelevant to this endpoint).
- [x] 7.3 Send `PUT .../first-fill` with a valid `first_fill_at_ms`; assert
  `200`.
- [x] 7.4 Inspect the repository directly: `FrozenExecutedEntryContext` is
  created; its `desired_entry` matches the seeded `applied_entry_package`;
  `first_fill_at_ms` is stored as supplied; `entry_bar_open_time_ms` is
  normalized onto the registered candle grid.
- [x] 7.5 Repeat the identical `PUT`: assert `200` again; assert the
  frozen context is unchanged (same values, and — if the repository/state
  exposes it — the same object identity, matching `apply_first_fill`'s
  no-op contract); assert no redundant `save` occurred (e.g. via a
  save-call counter on a wrapped/spied repository).
- [x] 7.6 Send a `PUT` with a different `first_fill_at_ms` for the same
  trade cycle: assert `409`; assert the stored frozen context is
  unchanged from step 7.4.

## 8. Shared-Writer Serialization Test

- [x] 8.1 Construct one real `StrategyInstanceKeyedMutexRegistry` and one
  real repository, shared between a test closed-bar writer path and a real
  `AbiExecutionEventOrchestrator`-backed first-fill HTTP path — no real ABI
  or Strategy Engine server is started.
- [x] 8.2 While a closed-bar writer thread holds the mutex for
  `instance-A` (block it deliberately, e.g. via a blocking fake stage
  inside the held critical section), issue a first-fill HTTP `PUT` for
  `instance-A` from another thread; assert the repository's `get(...)` for
  `instance-A` has not been called by the first-fill path while the mutex
  remains held.
- [x] 8.3 Release the closed-bar writer's hold on `instance-A`; assert the
  blocked first-fill request then proceeds and loads fresh state (i.e. any
  state mutation the closed-bar writer made before releasing is visible to
  the first-fill path's subsequent `get(...)`).
- [x] 8.4 While `instance-A`'s mutex is held, issue a first-fill `PUT` for
  a different `instance-B`; assert it is not blocked and completes without
  waiting for `instance-A`'s critical section to release.

## 9. Proposal-Pass Verification (this change)

- [x] 9.1 `npm exec -- openspec validate
  "runtime-abi-first-fill-http-integration-v1" --type change --strict` —
  passes (`Change 'runtime-abi-first-fill-http-integration-v1' is valid`).
- [x] 9.2 `npm exec -- openspec validate --all --strict` — passes (24
  passed, 0 failed).
- [x] 9.3 `git diff --check` — clean, no whitespace errors.
- [x] 9.4 `git status --short` — only files under this change's own
  directory staged/modified; no production code or test file touched.
- [x] 9.5 Confirmed: no production code, test file, existing main
  capability spec, or archived change is modified by this pass — only
  files under
  `openspec/changes/runtime-abi-first-fill-http-integration-v1/`
  (`.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`,
  `specs/http-abi-first-fill/spec.md`,
  `specs/runtime-production-composition/spec.md`) are touched.

## 10. Apply-Phase Verification (this pass)

- [x] 10.1 `ruff check` over the new/modified source and test files —
  passes.
- [x] 10.2 `ruff format --check` — passes (after one auto-format pass over
  `adapters/http/app.py` and the five new test files).
- [x] 10.3 `mypy` (strict) over `src/strategy_runtime/adapters/http/` and
  `src/strategy_runtime/bootstrap/` — passes, no issues.
- [x] 10.4 `python -m compileall` over `src` and `tests` — passes.
- [x] 10.5 Full `pytest` run — 828 passed, 0 failed. New coverage: 33 tests
  in `tests/integration/http/test_first_fill_endpoint.py` (contract +
  adapter-boundary), 1 in `tests/unit/test_http_app_architecture.py`
  (structural no-import guardrail), 8 in
  `tests/unit/bootstrap/test_first_fill_composition.py` (composition), 3 in
  `tests/integration/http/test_first_fill_vertical.py` (vertical), 2 in
  `tests/integration/http/test_first_fill_shared_writer_serialization.py`
  (shared-writer serialization); plus required updates to five existing
  `create_http_app(...)` call sites (`tests/integration/http/test_http_app.py`
  x4, `tests/integration/committed_bar/test_catalog_orchestrator_http_harness.py`
  x1) to pass the new required `process_first_fill` argument, with zero
  behavioral change to those tests.
