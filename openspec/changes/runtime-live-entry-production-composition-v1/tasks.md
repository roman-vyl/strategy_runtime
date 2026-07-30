## 1. Config and Readiness

- [x] 1.1 Add `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
  `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
  `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`, and
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` to `RuntimeConfig`
  (`config/model.py`), following the existing frozen-dataclass field style.
- [x] 1.2 Parse the three timeout variables as `float` in
  `load_runtime_config` (`config/loader.py`), following the existing
  `RUNTIME_PORT` int-parsing pattern (raise `ValueError` on a non-numeric
  string); pass the two base-URL strings through unparsed.
- [x] 1.3 Do not duplicate URL-shape or timeout-sign validation in
  `RuntimeConfig.__post_init__` or the loader beyond what is needed to parse
  the field's type; rely on each adapter's existing constructor validation
  (`HttpxStrategyEngineLiveEntryAdapter`/`...OpenTradeAdapter`'s
  `_build_client`, `HttpxAbiOpenPositionLookupAdapter.__init__`,
  `HttpxAbiEntryPackageAdapter.__init__`) to reject an invalid URL or a
  non-finite/non-positive timeout at construction time. Keep the two failure
  stages distinct (design.md §6-§7): missing/unparsable fields fail during
  config loading/parsing, before any client exists; malformed/non-finite
  fields fail only during adapter construction.
- [x] 1.4 Confirm the existing `build_application` `try/except Exception`
  block already covers every new failure mode (missing env var, unparsable
  timeout, invalid URL, adapter constructor rejection) and yields
  `ready=False` via the existing `create_http_app(ready=False, ...)` branch;
  extend that block only if a new failure mode would otherwise escape it.
- [x] 1.5 Add tests: valid five-field config constructs a ready application;
  each of missing/non-numeric/non-finite/non-positive timeout, and
  missing/malformed (non-`http`/`https`, no host) base URL, individually
  yields `ready=False` without raising past `build_application`.
- [x] 1.6 Confirm the five fields are unconditionally required for
  `build_application` to report `ready=True` — there is no construction path,
  parameter, mode, or flag that returns `ready=True` without them (design.md
  §2a).

## 2. Production Application Bundle / Composition Root

- [x] 2.1 Extend `build_application` to construct, after the existing utility
  contour and inside the existing readiness `try` block: the four outbound
  HTTP clients (§4), `OpenPositionResolver`, `StrategyUseCaseRouter`,
  `AbiEntryPackageExecutionBridge`, the shared repository and mutex registry
  (§3), `EntryReconciliationOrchestrator`, and `StrategyRuntimeOrchestrator`,
  using only their existing constructors, on the single ready construction
  path (there is no other path).
- [x] 2.2 Implement the closed production sink decision (design.md §2
  "Sink signature (closed)"): a thin, `None`-returning function that calls
  `StrategyRuntimeOrchestrator.process(unit)` and discards its return value,
  passed as `StrategyCycleHandoffBoundary(sink=<that function>)`. Do not use
  `.dispatch` as the sink (it would construct a second, discarded
  `StrategyCycleDispatchOutcome`).
- [x] 2.3 Remove the
  `strategy_cycle_handoff: StrategyCycleHandoffSink[...] | None = None`
  parameter from `build_application`'s public signature. `build_application`
  always constructs
  `StrategyCycleHandoffBoundary(sink=process_strategy_cycle)` using the thin
  sink from §2.2, unconditionally; no caller can substitute a different sink.
- [x] 2.4 Do not introduce a new top-level orchestrator, reconciliation
  component, or outbound adapter class; every new call in `build_application`
  must reference an existing, already-tested class or function.
- [x] 2.5 Confirm there is exactly one ready construction path: any successful
  `build_application(...)` call that returns `ready=True` has constructed the
  full semantic graph, the shared repository/mutex, and all four outbound
  HTTP clients — there is no utility-only `ready=True` result and no
  parameter that produces one.

## 3. Shared Repository and Mutex Wiring

- [x] 3.1 Construct exactly one `InMemoryStrategyInstanceRuntimeStateRepository`
  and exactly one `StrategyInstanceKeyedMutexRegistry` per `build_application`
  call, and pass the same two objects into the one constructed
  `StrategyRuntimeOrchestrator`.
- [x] 3.2 Keep both instances reachable from the composition-owned application
  bundle/state that `build_application` returns (e.g., as local variables the
  function can expose or attach to returned application state) so a future
  `I5` change can reuse them without reconstructing either and without a new
  build mode or parameter; do not make them unreachably private to a closure
  that only `StrategyRuntimeOrchestrator` can see.
- [x] 3.3 Add a guardrail test asserting `is`-identity: the exact repository
  object passed to `StrategyRuntimeOrchestrator`'s constructor is the same
  object reachable from the composition root, and likewise for the mutex
  registry.

## 4. Outbound Adapter/Bridge Construction

- [x] 4.1 Construct `HttpxStrategyEngineLiveEntryAdapter` and
  `HttpxStrategyEngineOpenTradeAdapter` from
  `RUNTIME_STRATEGY_ENGINE_BASE_URL` / `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`.
- [x] 4.2 Construct `HttpxAbiOpenPositionLookupAdapter` from
  `RUNTIME_ABI_BASE_URL` / `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`.
- [x] 4.3 Construct the existing `HttpxAbiEntryPackageAdapter` from
  `RUNTIME_ABI_BASE_URL` / `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`; do not
  modify this client beyond passing production config into its existing
  constructor.
- [x] 4.4 Wrap the ABI entry-package client in the existing
  `AbiEntryPackageExecutionBridge` and wire that bridge as
  `EntryReconciliationOrchestrator`'s `execution_port`.
- [x] 4.5 Wire the two Strategy Engine adapters into `StrategyUseCaseRouter`
  and the ABI open-position adapter into `OpenPositionResolver`, using their
  existing constructor parameter names.
- [x] 4.6 Add a guardrail test asserting each of the four HTTP clients is
  constructed exactly once per `build_application` call (e.g., by counting
  constructor invocations via a patched/spy constructor in a test, or by
  asserting `is`-identity of the client instance used across two simulated
  background cycles).

## 5. HTTP Client Lifecycle and Shutdown

- [x] 5.1 Introduce a single explicit composition lifecycle owner (e.g., a
  small composition-root object or closure) that holds references to all four
  constructed HTTP clients and exposes one operation that closes all of them.
- [x] 5.2 Wire that owner's close-all operation into exactly two paths: (a)
  startup rollback — invoked synchronously during `build_application`
  construction the moment a later client's constructor rejects its
  configuration, closing every client already constructed before returning
  the not-ready application; and (b) application shutdown (FastAPI `lifespan`
  or an equivalent mechanism) — invoked once construction succeeded and the
  application later shuts down. Do not pin a specific FastAPI shutdown API
  beyond "closes deterministically."
- [x] 5.3 On partial construction failure (a client fails to construct after
  earlier clients already succeeded), close every already-constructed client
  exactly once via startup rollback before `build_application` returns the
  not-ready application; those clients are not exposed in any returned
  application and are not closed again later.
- [x] 5.4 Ensure no code path other than the composition lifecycle owner ever
  calls `close()` on any of the four clients: not an HTTP request handler, not
  a background committed-bar cycle, not `StrategyRuntimeOrchestrator`,
  `OpenPositionResolver`, `StrategyUseCaseRouter`,
  `EntryReconciliationOrchestrator`, an outbound adapter after an individual
  call, or any other caller — only the composition lifecycle owner does,
  during startup rollback or application shutdown.
- [x] 5.5 Add tests: shutdown closes all four clients exactly once each after
  a successful ready construction; simulated partial-construction failure
  (e.g., a valid Engine config paired with an invalid ABI config) results in
  the Engine clients being closed exactly once via startup rollback and
  `ready=False`, with no leaked open client and no double-close.

## 6. Production `StrategyCycleHandoff` Sink and Utility-Contour Test Migration

- [x] 6.1 Confirm `StrategyCycleHandoffBoundary` requires no code change —
  only its production construction argument changes (§2.2/§2.3); its dispatch
  mechanics (attached/unattached sink, exception propagation) and its general
  capability to be constructed directly with an arbitrary sink (used by
  utility-level tests) stay exactly as implemented.
- [x] 6.2 Add a test proving every `build_application()` call that returns
  `ready=True` results in a `StrategyCycleHandoffBoundary` whose dispatch
  reaches the real `StrategyRuntimeOrchestrator` (e.g., via an observable side
  effect such as a repository state change or a recorded outbound-adapter
  call) — unconditionally, since no override parameter exists to bypass it.
- [x] 6.3 Add a guardrail test/static check confirming `build_application`'s
  public signature no longer declares a `strategy_cycle_handoff` (or
  equivalent) parameter; update every internal call site accordingly.
- [x] 6.4 Rewrite/rename
  `tests/integration/committed_bar/test_production_composition.py` — it must
  no longer call `build_application` to exercise the utility contour in
  isolation, since `build_application` now always constructs the complete
  production graph and requires full Engine/ABI configuration. Introduce a
  new utility-contour integration test file (e.g.
  `tests/integration/committed_bar/test_utility_contour.py`, or an equivalent
  name consistent with repository convention) and remove the old
  `test_production_composition...` name from any test that constructs utility
  components directly.
- [x] 6.5 In the new test, construct the utility contour directly from its
  own components — `FilesystemDeploymentCatalog`,
  `CommittedBarDeploymentSelector`, `JsonlProcessingJournal`,
  `StrategyCycleHandoffBoundary(sink=received.append)`, and
  `CommittedBarOrchestrator` — without calling `build_application`.
- [x] 6.6 Preserve every existing utility-level assertion from the old test in
  the new one: deployment selection (enabled/disabled/other-market
  filtering), exactly one dispatched `StrategyBarProcessingUnit`, its
  `source_path` and `strategy_instance_id` identity, and the existing journal
  event sequence
  (`committed_bar_orchestration_started`/`strategy_cycle_dispatch_succeeded`/
  `committed_bar_orchestration_completed`).
- [x] 6.7 Add or confirm a separate test that exercises `build_application`
  itself only with complete Engine/ABI production configuration (this may be
  the same test as §7's vertical E2E, or a dedicated composition-root test);
  `build_application` is never exercised with utility-only configuration
  again.

## 7. Background Vertical Live-Entry E2E

- [x] 7.1 Build a test harness that runs `build_application` with real
  production wiring (all five config fields pointing at in-process fake HTTP
  servers for Strategy Engine and ABI, following the existing
  `tests/contract/*` fake-server patterns) and drives it through a real
  `TestClient` request to `POST /v1/webhooks/closed-bar`. Implemented with a
  real-socket local HTTP server helper
  (`tests/integration/committed_bar/_fake_http_server.py`) rather than
  `httpx.MockTransport`, since the composition root exposes no transport
  -injection seam by design.
- [x] 7.2 Assert the HTTP-level contract independent of downstream outcome:
  a valid, ready webhook request registers exactly one background
  committed-bar handoff and returns `200 {"status":"accepted"}` before the
  background task's result is known.
- [x] 7.3 After the background task completes (await/flush it deterministically
  in the test, e.g. via `TestClient`'s synchronous background-task execution),
  assert the happy-path sequence: `position_open=false` → Engine returns a
  non-null `desired_entry` → reconciliation decides `APPLY` → the bridge
  request's `risk_multiplier` equals `source_state.risk_multiplier` (not any
  other source) → the fake ABI server returns `EntryPackageApplied` → the
  repository holds a saved `CurrentTradeCycle` for the strategy instance.
- [x] 7.4 Assert downstream outcomes are verified through repository state,
  recorded fake-server calls, and processing-journal records — never through
  HTTP status or body, which stays the already-sent `200 accepted` regardless
  of downstream outcome.

## 8. Failure/No-Op/Open-Trade-Unsupported E2E

- [x] 8.1 `desired_entry=null` with no existing current cycle → `NO_OP`: assert
  zero ABI entry-package calls and zero repository saves.
- [x] 8.2 `desired_entry=null` with an existing acknowledged current cycle →
  `CANCEL`: assert exactly one ABI entry-package call, and that the cycle is
  cleared only after the fake ABI server returns `EntryPackageAbsent` (not
  optimistically before it).
- [x] 8.3 ABI open-position lookup failure (timeout, network failure, protocol
  error, public error — each individually): assert Strategy Engine is never
  called and no repository save occurs.
- [x] 8.4 Strategy Engine projection failure (timeout, network failure,
  protocol error, public error — each individually): assert the ABI
  entry-package endpoint is never called and no repository save occurs.
- [x] 8.5 ABI entry-package failure (timeout, network failure, protocol error,
  public error — each individually): at the component level, assert
  `EntryReconciliationExecutionError` propagates uncaught out of
  `EntryReconciliationOrchestrator.execute(...)` and
  `StrategyRuntimeOrchestrator.process(...)`. At the full
  `TestClient`/background-contour level, assert the observable result is a
  failed `StrategyCycleDispatchOutcome` journaled by
  `CommittedBarOrchestrator` (design.md §9 propagation rule) — not an
  exception escaping the HTTP/background boundary — that the repository holds
  no new save for that cycle, and that no call depending on the failed one is
  invoked. Timeout/protocol-error/public-error sub-cases are exercised
  end-to-end; the network-failure sub-case is skipped with an explicit reason
  (ABI open-position and entry-package share one `RUNTIME_ABI_BASE_URL`, so an
  unreachable ABI host is already exercised by the open-position lookup
  parametrization in §8.3 — there is no per-adapter base-URL override to
  isolate it to entry-package alone). The component-level uncaught
  -propagation identity is additionally pinned by a direct assertion; the full
  propagation mechanics were already proven by the archived
  `entry-reconciliation-orchestrator-v1`/`closed-bar-runtime-orchestration-v1`
  fake-based suites and are not re-derived here.
- [x] 8.6 `position_open=true`: assert the open-trade Engine adapter may be
  called by `StrategyUseCaseRouter`, but `StrategyRuntimeOrchestrator` still
  raises `OpenTradeProjectionUnsupportedError`, which propagates the same way
  as 8.5 (uncaught out of the semantic core, caught only by
  `CommittedBarOrchestrator`); assert no repository save occurs and the failed
  dispatch outcome is journaled — the open-trade branch remains explicitly
  unsupported end to end in production composition.
- [x] 8.7 For each of the three outbound boundaries individually (ABI
  open-position lookup, Strategy Engine projection, ABI entry-package call),
  assert: exactly one call attempt (no automatic retry), the bounded timeout
  from config is honored, and no call dependent on the failed one is invoked.
- [x] 8.8 Assert every failure-path outcome is journaled through the existing
  `JsonlProcessingJournal` failed-dispatch-outcome mechanism, with no new
  journal event type introduced.

## 9. Architecture and Scope Guardrails

- [x] 9.1 Add a guardrail test proving `build_application` constructs and
  wires `StrategyRuntimeOrchestrator` (via the thin sink) as
  `StrategyCycleHandoffBoundary`'s sink unconditionally — there is no code
  path that returns `ready=True` without it, and no other class satisfies
  that role.
- [x] 9.2 Add a guardrail test proving exactly one repository instance and one
  keyed-mutex-registry instance are shared across the entire constructed
  graph (§3.3, restated here as a scope guardrail alongside the existing
  `test_orchestrator_composes_existing_components`-style assertions).
- [x] 9.3 Add a guardrail test proving the four HTTP clients are not
  constructed inside `CommittedBarOrchestrator`, `StrategyCycleHandoffBoundary`,
  or per-request/per-cycle code — only inside `build_application`'s
  composition step.
- [x] 9.4 Confirm no change to `adapters/http/app.py` request/response models,
  status codes, the `BackgroundTasks` handoff mechanism, or any existing test
  in `tests/integration/http/test_http_app.py` — extend that test module only
  with new assertions if strictly additive, never by modifying an existing
  assertion's expected behavior. (One additive, backward-compatible optional
  `lifespan` parameter was added to `create_http_app` to give the composition
  root a standard shutdown hook; no existing parameter, model, status code, or
  test assertion changed, and the full existing `test_http_app.py` suite
  passes unmodified.)
- [x] 9.5 Confirm no change to `EntryReconciliationOrchestrator`,
  `StrategyRuntimeOrchestrator`, `OpenPositionResolver`,
  `StrategyUseCaseRouter`, the three `I4c` HTTP adapters, the entry-execution
  bridge, or the existing `AbiEntryPackagePort` HTTP client beyond passing
  production configuration into their existing constructors.
- [x] 9.6 Confirm `infrastructure/runtime_state/sqlite_repository.py` remains
  unimplemented and no queue/broker/worker/retry/replay/deduplication module is
  added anywhere in the diff.
- [x] 9.7 Confirm no canonical system-plan file or archived OpenSpec change is
  edited by this change.
- [x] 9.8 Add a guardrail test/static check proving `build_application`'s
  signature declares no `strategy_cycle_handoff` (or equivalent) parameter
  (e.g., via `inspect.signature` in a test).
- [x] 9.9 Add a guardrail test proving there is no hidden utility-only ready
  bootstrap path: every `ready=True` application constructed by
  `build_application` has the four outbound HTTP clients and the shared
  repository/mutex reachable and constructed.
- [x] 9.10 Add a guardrail test/assertion proving the shared repository and
  keyed-mutex-registry instances are reachable from the composition-owned
  application bundle/state (for a future `I5` to reuse), not via any
  alternative build mode, parameter, or flag.

## 10. Full Verification

- [x] 10.1 Run the new config, composition-root, lifecycle, vertical E2E,
  failure-path, utility-contour-migration, and architecture-guardrail tests
  added by this change.
- [x] 10.2 Run the complete Runtime pytest suite, Ruff lint and format checks,
  mypy, and Python compilation checks using the repository's established
  verification commands. `make lint`, `make typecheck`, `make test`
  (638 passed, 1 documented skip), and `python -m compileall` all pass.
  `make format-check` reports four files
  (`src/strategy_runtime/runtime/abi/entry_package_codec.py`,
  `entry_package_http.py`, `tests/contract/abi/test_entry_package_client.py`,
  `test_entry_package_openapi.py`) as needing reformatting; this drift
  predates this change (confirmed via `git show HEAD:<path> | ruff format
  --diff -` against the pre-`I4d` commit, unrelated to any file this change
  touches) and is left unmodified rather than silently reformatted as
  out-of-scope drift.
- [x] 10.3 Run `npm run openspec:validate` (repository-pinned
  `openspec validate --all --strict --no-interactive`). 20/20 passed.
- [x] 10.4 Run `openspec validate runtime-live-entry-production-composition-v1
  --strict --no-interactive` for this change specifically. Valid.
- [x] 10.5 Run `git diff --check`. Clean.
- [x] 10.6 Audit the final implementation diff to confirm it is limited to
  config, the composition root, HTTP client lifecycle ownership, the
  production handoff sink, the utility-contour test migration, and their
  tests, with every deferred component (`I5`, `I6`, open-trade gate, durable
  persistence, `http-closed-bar` contract) unchanged.

## 11. Documentation Sync and Archive

- [ ] 11.1 Update `runtime-master-plan.md`, `runtime-abi-entry-delivery-map.md`,
  `runtime-live-entry-production-integration-plan.md`, and
  `runtime-abi-entry-reconciliation-master-plan.md` to mark `I4d` implemented
  and verified, matching the exact composition graph actually delivered.
  Not performed by this pass; no system-plan file has been edited.
- [ ] 11.2 Regenerate `runtime-abi-entry-delivery-map.fragment.html` and
  `runtime-abi-entry-delivery-map.html` per the existing update procedure once
  `I4d`'s checklist entries flip to done. Not performed by this pass.
- [ ] 11.3 Archive `runtime-live-entry-production-composition-v1` only after
  verification (§10) is complete and the documentation sync above has landed
  in the same change as the implementation; not performed by this pass —
  awaiting an explicit request to sync docs and archive.
