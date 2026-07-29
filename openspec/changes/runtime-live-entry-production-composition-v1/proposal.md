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

- Compose exactly one production graph in `build_application`, reached only
  through the default construction mode (`strategy_cycle_handoff` not
  supplied): existing utility contour → `StrategyCycleHandoffBoundary` → a
  thin, `None`-returning sink function that calls the existing
  `StrategyRuntimeOrchestrator.process(unit)` and discards its result → shared
  `StrategyInstanceRuntimeStateRepository` and shared
  `StrategyInstanceKeyedMutexRegistry` → `OpenPositionResolver` (the existing
  `HttpxAbiOpenPositionLookupAdapter`) → `StrategyUseCaseRouter` (the existing
  `HttpxStrategyEngineLiveEntryAdapter` / `HttpxStrategyEngineOpenTradeAdapter`)
  → the existing `EntryReconciliationOrchestrator` → the existing
  `AbiEntryPackageExecutionBridge` over the existing `HttpxAbiEntryPackageAdapter`.
  No new top-level orchestrator, reconciliation component, or outbound adapter
  is introduced; every component composed here already exists and is already
  tested in isolation. When an explicit `strategy_cycle_handoff` override is
  supplied instead (the existing test seam), none of the semantic graph or the
  four outbound HTTP clients is constructed, and the five config fields below
  are not required.
- Add five required production config inputs
  (`RUNTIME_STRATEGY_ENGINE_BASE_URL`, `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_BASE_URL`, `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`), required only for the default
  construction mode above, following the existing `RUNTIME_*` convention in
  `strategy_runtime.config.loader`. Invalid or missing production config fails
  startup readiness closed (`ready=False`), matching the existing not-ready
  pattern already used for invalid `RuntimeConfig`. Resource construction may
  proceed partway before an invalid field is rejected by a later adapter
  constructor; a partially constructed *ready* production graph is never
  returned — every client already constructed is closed first.
- Give the composition root single, explicit ownership of the four production
  HTTP clients it constructs (`HttpxStrategyEngineLiveEntryAdapter`,
  `HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
  and the existing `HttpxAbiEntryPackageAdapter`): each is constructed exactly
  once at application construction, reused across every background committed-bar
  cycle, and closed exactly once at application shutdown; a partial
  construction failure closes every client already constructed instead of
  leaking a connection.
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
  the four HTTP clients are not constructed per request, and the default
  production sink is the thin function calling
  `StrategyRuntimeOrchestrator.process`, not a test override, unless one is
  explicitly supplied.

## Capabilities

### New Capabilities

- `runtime-production-composition`: Defines the production composition root —
  construction graph, shared repository/mutex ownership, outbound HTTP client
  ownership and lifecycle, the five config inputs and fail-closed readiness
  rule, the production `StrategyCycleHandoffBoundary` sink, the two distinct
  acknowledgement boundaries (MDS webhook vs. ABI entry-package), fail-closed
  state-save semantics, and the accepted non-durable Live V1 limitation
  (in-memory repository; a process restart may lose an in-flight background
  cycle).

### Modified Capabilities

- `strategy-cycle-handoff`: Add the requirement that production composition
  attaches a thin, `None`-returning sink function that calls the existing
  `StrategyRuntimeOrchestrator.process` as the boundary's production sink,
  replacing the previously unattached (no-op) production default; the
  boundary's own dispatch mechanics (attached/unattached sink behavior,
  exception propagation) are unchanged.

## Impact

- `strategy_runtime.bootstrap.application.build_application` gains the
  construction of the semantic core and the four outbound adapters/bridge; no
  other utility-contour behavior changes.
- `strategy_runtime.config.model.RuntimeConfig` and
  `strategy_runtime.config.loader.load_runtime_config` gain five required
  fields; existing fields and validation are unchanged.
- No change to `strategy_runtime.adapters.http.app` request/response models,
  status codes, or the existing background-task acknowledgement test.
- No change to `EntryReconciliationOrchestrator`, `StrategyRuntimeOrchestrator`,
  `OpenPositionResolver`, `StrategyUseCaseRouter`, the three `I4c` HTTP
  adapters, the entry-execution bridge, or the existing `AbiEntryPackagePort`
  HTTP client beyond their construction inside the composition root.
- `infrastructure/runtime_state/sqlite_repository.py` remains an empty
  placeholder; no durable repository, queue, retry, or deduplication mechanism
  is introduced.
- No canonical system-plan or archived OpenSpec file is edited by this change.
