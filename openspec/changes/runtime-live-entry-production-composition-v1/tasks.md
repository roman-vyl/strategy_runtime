## 1. Config and Readiness

- [ ] 1.1 Add `RUNTIME_STRATEGY_ENGINE_BASE_URL`,
  `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
  `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`, and
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` to `RuntimeConfig`
  (`config/model.py`), following the existing frozen-dataclass field style.
- [ ] 1.2 Parse the three timeout variables as `float` in
  `load_runtime_config` (`config/loader.py`), following the existing
  `RUNTIME_PORT` int-parsing pattern (raise `ValueError` on a non-numeric
  string); pass the two base-URL strings through unparsed.
- [ ] 1.3 Do not duplicate URL-shape or timeout-sign validation in
  `RuntimeConfig.__post_init__` or the loader beyond what is needed to parse
  the field's type; rely on each adapter's existing constructor validation
  (`HttpxStrategyEngineLiveEntryAdapter`/`...OpenTradeAdapter`'s
  `_build_client`, `HttpxAbiOpenPositionLookupAdapter.__init__`,
  `HttpxAbiEntryPackageAdapter.__init__`) to reject an invalid URL or a
  non-finite/non-positive timeout at construction time.
- [ ] 1.4 Confirm the existing `build_application` `try/except Exception`
  block already covers every new failure mode (missing env var, unparsable
  timeout, invalid URL, adapter constructor rejection) and yields
  `ready=False` via the existing `create_http_app(ready=False, ...)` branch;
  extend that block only if a new failure mode would otherwise escape it.
- [ ] 1.5 Add tests: valid five-field config constructs a ready application;
  each of missing/non-numeric/non-finite/non-positive timeout, and
  missing/malformed (non-`http`/`https`, no host) base URL, individually
  yields `ready=False` without raising past `build_application`.

## 2. Production Application Bundle / Composition Root

- [ ] 2.1 Extend `build_application` to construct, after the existing utility
  contour and inside the existing readiness `try` block: the four outbound
  HTTP clients (§4), `OpenPositionResolver`, `StrategyUseCaseRouter`,
  `AbiEntryPackageExecutionBridge`, the shared repository and mutex registry
  (§3), `EntryReconciliationOrchestrator`, and `StrategyRuntimeOrchestrator`,
  using only their existing constructors.
- [ ] 2.2 Decide and document the exact production sink closure passed to
  `StrategyCycleHandoffBoundary` (a thin wrapper discarding
  `StrategyRuntimeOrchestrator.process`'s or `.dispatch`'s return value; see
  design.md §2 "Sink signature note"); prefer `dispatch` unless implementation
  finds a concrete reason to call `process` directly.
- [ ] 2.3 Preserve the existing `strategy_cycle_handoff` override parameter on
  `build_application` exactly as today: when supplied, it replaces the
  production sink; when omitted, the composed `StrategyRuntimeOrchestrator`
  sink is used.
- [ ] 2.4 Do not introduce a new top-level orchestrator, reconciliation
  component, or outbound adapter class; every new call in `build_application`
  must reference an existing, already-tested class or function.

## 3. Shared Repository and Mutex Wiring

- [ ] 3.1 Construct exactly one `InMemoryStrategyInstanceRuntimeStateRepository`
  and exactly one `StrategyInstanceKeyedMutexRegistry` per `build_application`
  call, and pass the same two objects into the one constructed
  `StrategyRuntimeOrchestrator`.
- [ ] 3.2 Keep both instances reachable from the composition root (e.g., as
  local variables the function can expose or attach to returned application
  state) so a future `I5` change can reuse them without reconstructing either;
  do not make them unreachably private to a closure that only
  `StrategyRuntimeOrchestrator` can see.
- [ ] 3.3 Add a guardrail test asserting `is`-identity: the exact repository
  object passed to `StrategyRuntimeOrchestrator`'s constructor is the same
  object reachable from the composition root, and likewise for the mutex
  registry.

## 4. Outbound Adapter/Bridge Construction

- [ ] 4.1 Construct `HttpxStrategyEngineLiveEntryAdapter` and
  `HttpxStrategyEngineOpenTradeAdapter` from
  `RUNTIME_STRATEGY_ENGINE_BASE_URL` / `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`.
- [ ] 4.2 Construct `HttpxAbiOpenPositionLookupAdapter` from
  `RUNTIME_ABI_BASE_URL` / `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`.
- [ ] 4.3 Construct the existing `HttpxAbiEntryPackageAdapter` from
  `RUNTIME_ABI_BASE_URL` / `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`; do not
  modify this client beyond passing production config into its existing
  constructor.
- [ ] 4.4 Wrap the ABI entry-package client in the existing
  `AbiEntryPackageExecutionBridge` and wire that bridge as
  `EntryReconciliationOrchestrator`'s `execution_port`.
- [ ] 4.5 Wire the two Strategy Engine adapters into `StrategyUseCaseRouter`
  and the ABI open-position adapter into `OpenPositionResolver`, using their
  existing constructor parameter names.
- [ ] 4.6 Add a guardrail test asserting each of the four HTTP clients is
  constructed exactly once per `build_application` call (e.g., by counting
  constructor invocations via a patched/spy constructor in a test, or by
  asserting `is`-identity of the client instance used across two simulated
  background cycles).

## 5. HTTP Client Lifecycle and Shutdown

- [ ] 5.1 Introduce a single explicit owner (e.g., a small composition-root
  object or closure) that holds references to all four constructed HTTP
  clients and exposes one operation that closes all of them.
- [ ] 5.2 Wire that owner's close operation into the application's shutdown
  path (FastAPI `lifespan` or an equivalent mechanism); do not pin the
  specific FastAPI shutdown API in this task beyond "closes deterministically
  on application shutdown."
- [ ] 5.3 On partial construction failure (a client fails to construct after
  earlier clients already succeeded), close every already-constructed client
  before `build_application` returns the not-ready application.
- [ ] 5.4 Ensure no per-request or per-background-cycle code path calls
  `close()` on any of the four clients; only the shutdown owner does.
- [ ] 5.5 Add tests: shutdown closes all four clients exactly once each;
  simulated partial-construction failure (e.g., a valid Engine config paired
  with an invalid ABI config) results in the Engine clients being closed and
  `ready=False`, with no leaked open client.

## 6. Production `StrategyCycleHandoff` Sink

- [ ] 6.1 Confirm `StrategyCycleHandoffBoundary` requires no code change —
  only its production construction argument changes (§2.2); its dispatch
  mechanics (attached/unattached sink, exception propagation) stay exactly as
  implemented.
- [ ] 6.2 Add a test proving the default `build_application()` call (no
  `strategy_cycle_handoff` override) results in a `StrategyCycleHandoffBoundary`
  whose dispatch reaches the real `StrategyRuntimeOrchestrator` (e.g., via an
  observable side effect such as a repository state change or a recorded
  outbound-adapter call), not an unattached no-op sink.
- [ ] 6.3 Confirm the existing `strategy_cycle_handoff` override parameter
  still fully replaces the production sink when supplied, matching the
  existing `test_production_composition_runs_the_complete_utility_contour`
  usage pattern.

## 7. Background Vertical Live-Entry E2E

- [ ] 7.1 Build a test harness that runs `build_application` with real
  production wiring (all five config fields pointing at in-process fake HTTP
  servers for Strategy Engine and ABI, following the existing
  `tests/contract/*` fake-server patterns) and drives it through a real
  `TestClient` request to `POST /v1/webhooks/closed-bar`.
- [ ] 7.2 Assert the HTTP-level contract independent of downstream outcome:
  a valid, ready webhook request registers exactly one background
  committed-bar handoff and returns `200 {"status":"accepted"}` before the
  background task's result is known.
- [ ] 7.3 After the background task completes (await/flush it deterministically
  in the test, e.g. via `TestClient`'s synchronous background-task execution),
  assert the happy-path sequence: `position_open=false` → Engine returns a
  non-null `desired_entry` → reconciliation decides `APPLY` → the bridge
  request's `risk_multiplier` equals `source_state.risk_multiplier` (not any
  other source) → the fake ABI server returns `EntryPackageApplied` → the
  repository holds a saved `CurrentTradeCycle` for the strategy instance.
- [ ] 7.4 Assert downstream outcomes are verified through repository state,
  recorded fake-server calls, and processing-journal records — never through
  HTTP status or body, which stays the already-sent `200 accepted` regardless
  of downstream outcome.

## 8. Failure/No-Op/Open-Trade-Unsupported E2E

- [ ] 8.1 `desired_entry=null` with no existing current cycle → `NO_OP`: assert
  zero ABI entry-package calls and zero repository saves.
- [ ] 8.2 `desired_entry=null` with an existing acknowledged current cycle →
  `CANCEL`: assert exactly one ABI entry-package call, and that the cycle is
  cleared only after the fake ABI server returns `EntryPackageAbsent` (not
  optimistically before it).
- [ ] 8.3 ABI open-position lookup failure (timeout, network failure, protocol
  error, public error — each individually): assert Strategy Engine is never
  called and no repository save occurs.
- [ ] 8.4 Strategy Engine projection failure (timeout, network failure,
  protocol error, public error — each individually): assert the ABI
  entry-package endpoint is never called and no repository save occurs.
- [ ] 8.5 ABI entry-package failure (timeout, network failure, protocol error,
  public error — each individually): assert `EntryReconciliationExecutionError`
  propagates and no repository save occurs; the prior aggregate is unchanged.
- [ ] 8.6 `position_open=true`: assert the open-trade Engine adapter may be
  called by `StrategyUseCaseRouter`, but `StrategyRuntimeOrchestrator` still
  raises `OpenTradeProjectionUnsupportedError`, no repository save occurs, and
  the failed dispatch outcome is journaled — the open-trade branch remains
  explicitly unsupported end to end in production composition.
- [ ] 8.7 For each of the three outbound boundaries individually (ABI
  open-position lookup, Strategy Engine projection, ABI entry-package call),
  assert: exactly one call attempt (no automatic retry), the bounded timeout
  from config is honored, and no call dependent on the failed one is invoked.
- [ ] 8.8 Assert every failure-path outcome is journaled through the existing
  `JsonlProcessingJournal` failed-dispatch-outcome mechanism, with no new
  journal event type introduced.

## 9. Architecture and Scope Guardrails

- [ ] 9.1 Add a guardrail test proving `build_application`'s production path
  (no `strategy_cycle_handoff` override) constructs and wires
  `StrategyRuntimeOrchestrator` as `StrategyCycleHandoffBoundary`'s sink, and
  that no other class satisfies that role.
- [ ] 9.2 Add a guardrail test proving exactly one repository instance and one
  keyed-mutex-registry instance are shared across the entire constructed
  graph (§3.3, restated here as a scope guardrail alongside the existing
  `test_orchestrator_composes_existing_components`-style assertions).
- [ ] 9.3 Add a guardrail test proving the four HTTP clients are not
  constructed inside `CommittedBarOrchestrator`, `StrategyCycleHandoffBoundary`,
  or per-request/per-cycle code — only inside `build_application`'s
  composition step.
- [ ] 9.4 Confirm no change to `adapters/http/app.py` request/response models,
  status codes, the `BackgroundTasks` handoff mechanism, or any existing test
  in `tests/integration/http/test_http_app.py` — extend that test module only
  with new assertions if strictly additive, never by modifying an existing
  assertion's expected behavior.
- [ ] 9.5 Confirm no change to `EntryReconciliationOrchestrator`,
  `StrategyRuntimeOrchestrator`, `OpenPositionResolver`,
  `StrategyUseCaseRouter`, the three `I4c` HTTP adapters, the entry-execution
  bridge, or the existing `AbiEntryPackagePort` HTTP client beyond passing
  production configuration into their existing constructors.
- [ ] 9.6 Confirm `infrastructure/runtime_state/sqlite_repository.py` remains
  unimplemented and no queue/broker/worker/retry/replay/deduplication module is
  added anywhere in the diff.
- [ ] 9.7 Confirm no canonical system-plan file or archived OpenSpec change is
  edited by this change.

## 10. Full Verification

- [ ] 10.1 Run the new config, composition-root, lifecycle, vertical E2E,
  failure-path, and architecture-guardrail tests added by this change.
- [ ] 10.2 Run the complete Runtime pytest suite, Ruff lint and format checks,
  mypy, and Python compilation checks using the repository's established
  verification commands.
- [ ] 10.3 Run `npm run openspec:validate` (repository-pinned
  `openspec validate --all --strict --no-interactive`).
- [ ] 10.4 Run `openspec validate runtime-live-entry-production-composition-v1
  --strict --no-interactive` for this change specifically.
- [ ] 10.5 Run `git diff --check`.
- [ ] 10.6 Audit the final implementation diff to confirm it is limited to
  config, the composition root, HTTP client lifecycle ownership, the
  production handoff sink, and their tests, with every deferred component
  (`I5`, `I6`, open-trade gate, durable persistence, `http-closed-bar`
  contract) unchanged.

## 11. Documentation Sync and Archive

- [ ] 11.1 Update `runtime-master-plan.md`, `runtime-abi-entry-delivery-map.md`,
  `runtime-live-entry-production-integration-plan.md`, and
  `runtime-abi-entry-reconciliation-master-plan.md` to mark `I4d` implemented
  and verified, matching the exact composition graph actually delivered.
  (Deferred until implementation lands — no system-plan file is edited by
  this OpenSpec change itself.)
- [ ] 11.2 Regenerate `runtime-abi-entry-delivery-map.fragment.html` and
  `runtime-abi-entry-delivery-map.html` per the existing update procedure once
  `I4d`'s checklist entries flip to done. (Deferred until implementation
  lands.)
- [ ] 11.3 Archive `runtime-live-entry-production-composition-v1` only after
  verification (§10) is complete and the documentation sync above has landed
  in the same change as the implementation; this OpenSpec authoring pass does
  not perform the archive.
