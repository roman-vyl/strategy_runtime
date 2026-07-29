## Why

`I4c` (`runtime-production-outbound-adapters-v1`) implemented and contract-tested
the three missing production HTTP adapters (`StrategyEngineLiveEntryPort`,
`StrategyEngineOpenTradePort`, `AbiOpenPositionLookupPort`) and the
`EntryReconciliationExecutionPort` → `AbiEntryPackagePort` bridge, in isolation.
None of them is reachable from production: `build_application` still composes
only the utility contour (`FilesystemDeploymentCatalog` →
`CommittedBarDeploymentSelector` → `CommittedBarOrchestrator` →
`StrategyCycleHandoffBoundary`) and stops at an unattached
`StrategyCycleHandoffSink`. The already-implemented `StrategyRuntimeOrchestrator`
critical section (state repository, keyed mutex, open-position resolver,
use-case router, `EntryReconciliationOrchestrator`) is fully tested but never
constructed by production code.

`I4d` closes that gap by composition only: it wires the existing semantic core
and the four existing outbound dependencies into one production graph behind
the existing, unchanged `POST /v1/webhooks/closed-bar` HTTP boundary, adds the
five outbound-service config inputs required to construct real HTTP adapters,
and gives the resulting HTTP clients a single explicit owner across
construction and shutdown. It proves the live-entry vertical slice — MDS
webhook → background handoff → Engine projection → ABI reconciliation →
acknowledged Runtime state — with a real HTTP-shaped transport on the Runtime
side, while ABI may remain a fake HTTP server.

`build_application` becomes the single production composition root with
exactly one ready construction path: it no longer accepts a caller-supplied
handoff override, and a `ready=True` result always means the complete
production graph — semantic core, shared repository/mutex, and all four
outbound HTTP clients — was constructed. There is no alternative utility-only
`ready=True` result from this function. The utility contour's own isolated
testability is preserved by constructing its components directly in a test,
not by a `build_application` bypass.

This change does not redesign orchestration, reconciliation, or any outbound
wire contract. It does not change the existing `http-closed-bar` HTTP contract:
the webhook keeps returning `{"status":"accepted"}` immediately after
validation and readiness, independent of downstream processing, exactly as the
current `http-closed-bar` capability already specifies and as the existing
`test_acknowledgement_is_sent_before_background_task_completes` test already
proves. `I4d` only changes what the existing background handoff does after
that acknowledgement: it is composed all the way through the semantic core and
the real outbound adapters instead of stopping at an unattached sink.

## What Changes

- Compose exactly one production graph in `build_application`, unconditionally:
  existing utility contour → `StrategyCycleHandoffBoundary` → a thin,
  `None`-returning sink function that calls the existing
  `StrategyRuntimeOrchestrator.process(unit)` and discards its result → shared
  `StrategyInstanceRuntimeStateRepository` and shared
  `StrategyInstanceKeyedMutexRegistry` → `OpenPositionResolver` (the existing
  `HttpxAbiOpenPositionLookupAdapter`) → `StrategyUseCaseRouter` (the existing
  `HttpxStrategyEngineLiveEntryAdapter` / `HttpxStrategyEngineOpenTradeAdapter`)
  → the existing `EntryReconciliationOrchestrator` → the existing
  `AbiEntryPackageExecutionBridge` over the existing `HttpxAbiEntryPackageAdapter`.
  No new top-level orchestrator, reconciliation component, or outbound adapter
  is introduced; every component composed here already exists and is already
  tested in isolation.
- Remove the `strategy_cycle_handoff: StrategyCycleHandoffSink[...] | None =
  None` parameter from `build_application`'s public signature. There is no
  caller-supplied composition override in production code after this change;
  `build_application` always constructs
  `StrategyCycleHandoffBoundary(sink=process_strategy_cycle)` using the thin
  sink above.
- Add five required production config inputs
  (`RUNTIME_STRATEGY_ENGINE_BASE_URL`, `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_BASE_URL`, `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`), unconditionally required for
  any `ready=True` result of `build_application`, following the existing
  `RUNTIME_*` convention in `strategy_runtime.config.loader`. A missing
  required variable or an unparsable timeout string fails closed before any
  outbound HTTP client is constructed; a value that parses successfully but is
  rejected by an adapter constructor (malformed URL, non-finite/non-positive
  timeout) fails closed after zero or more earlier clients already exist —
  either way, every client already constructed is closed via startup rollback
  and `ready=False` is returned. No partially constructed *ready* production
  graph is ever returned.
- Give the composition root single, explicit ownership of the four production
  HTTP clients it constructs (`HttpxStrategyEngineLiveEntryAdapter`,
  `HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
  and the existing `HttpxAbiEntryPackageAdapter`): each is constructed exactly
  once at application construction, reused across every background committed-bar
  cycle, and closed exactly once by that same lifecycle owner — during startup
  rollback if construction fails partway, or during application shutdown if
  construction succeeded. No other caller ever closes an owned client.
- Rewrite the existing
  `tests/integration/committed_bar/test_production_composition.py` test as a
  dedicated utility-contour integration test that constructs
  `FilesystemDeploymentCatalog`, `CommittedBarDeploymentSelector`,
  `JsonlProcessingJournal`, `StrategyCycleHandoffBoundary`, and
  `CommittedBarOrchestrator` directly, without calling `build_application` —
  since `build_application` no longer has a utility-only `ready=True` path to
  exercise. All of its existing utility-level assertions (deployment
  selection, one dispatched unit, source path/identity, journal event
  sequence) are preserved in the new test.
- Keep the existing `POST /v1/webhooks/closed-bar` HTTP contract, background
  `BackgroundTasks` handoff, and immediate `{"status":"accepted"}`
  acknowledgement unchanged in observable behavior; `http-closed-bar` is not
  modified by this change.
- Distinguish, in design and tests, the immediate MDS webhook acknowledgement
  (`200 {"status":"accepted"}`, a transport-level acceptance fact) from the
  ABI entry-package acknowledgement (`EntryPackageApplied` /
  `EntryPackageAbsent`, the only event that authorizes reconciliation state
  application and repository save). A downstream failure after the HTTP
  acknowledgement never changes the already-sent HTTP response, never
  fabricates a confirmation, and never saves an unconfirmed `CurrentTradeCycle`;
  it is recorded through the existing processing-journal/outcome mechanism.
- Add a vertical background E2E test exercising the full production composition
  through a real `TestClient` request and a real (in-process fake-server) HTTP
  transport for all four outbound adapters, covering the happy path, `NO_OP`,
  `CANCEL`, each outbound failure branch individually, and the explicitly
  unsupported open-trade branch.
- Add architecture/scope guardrail tests proving exactly one repository
  instance and one keyed-mutex-registry instance are shared across the graph,
  the four HTTP clients are not constructed per request, `build_application`'s
  signature declares no composition-override parameter, and every `ready=True`
  application has the complete graph — there is no hidden utility-only ready
  path.

## Capabilities

### New Capabilities

- `runtime-production-composition`: Defines the production composition root —
  the single ready construction path (no caller-supplied override), the
  construction graph, shared repository/mutex ownership, outbound HTTP client
  ownership and lifecycle (startup rollback vs. shutdown, owned by one
  lifecycle owner), the five unconditionally required config inputs and
  fail-closed readiness rule, the production `StrategyCycleHandoffBoundary`
  sink, the two distinct acknowledgement boundaries (MDS webhook vs. ABI
  entry-package), fail-closed state-save semantics, and the accepted
  non-durable Live V1 limitation (in-memory repository; a process restart may
  lose an in-flight background cycle).

### Modified Capabilities

- `strategy-cycle-handoff`: Add the requirement that production composition
  unconditionally attaches a thin, `None`-returning sink function that calls
  the existing `StrategyRuntimeOrchestrator.process` as the boundary's
  production sink, replacing the previously unattached (no-op) production
  default; `build_application` accepts no parameter that could replace this
  sink. The boundary's own dispatch mechanics (attached/unattached sink
  behavior, exception propagation) and its existing general capability to be
  constructed directly with an arbitrary sink in utility-level tests are
  unchanged.

## Impact

- `strategy_runtime.bootstrap.application.build_application` gains
  construction of the semantic core and the four outbound adapters/bridge, and
  loses its `strategy_cycle_handoff` parameter — a breaking change to that
  function's public signature. Every existing call site that passes
  `strategy_cycle_handoff` must be updated.
- `strategy_runtime.config.model.RuntimeConfig` and
  `strategy_runtime.config.loader.load_runtime_config` gain five required
  fields; existing fields and validation are unchanged.
- No change to `strategy_runtime.adapters.http.app` request/response models,
  status codes, or the existing background-task acknowledgement test.
- No change to `EntryReconciliationOrchestrator`, `StrategyRuntimeOrchestrator`,
  `OpenPositionResolver`, `StrategyUseCaseRouter`, the three `I4c` HTTP
  adapters, the entry-execution bridge, or the existing `AbiEntryPackagePort`
  HTTP client beyond their construction inside the composition root.
- `tests/integration/committed_bar/test_production_composition.py` is
  rewritten/renamed to a dedicated utility-contour test that no longer calls
  `build_application`; a separate test exercises `build_application` itself
  with complete production configuration.
- `infrastructure/runtime_state/sqlite_repository.py` remains an empty
  placeholder; no durable repository, queue, retry, or deduplication mechanism
  is introduced.
- No canonical system-plan or archived OpenSpec file is edited by this change.
