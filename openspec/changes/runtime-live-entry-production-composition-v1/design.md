## Context

`I4a`–`I4c` implemented and archived the complete semantic live-entry core
(`StrategyRuntimeOrchestrator`, `EntryReconciliationOrchestrator`, the
in-memory state repository, the keyed-mutex registry) and the four production
outbound dependencies (`HttpxStrategyEngineLiveEntryAdapter`,
`HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`,
`AbiEntryPackageExecutionBridge` over the pre-existing
`HttpxAbiEntryPackageAdapter`). Every one of these components is unit- or
contract-tested in isolation. None is constructed by
`strategy_runtime.bootstrap.application.build_application`, which today stops
at:

```text
FilesystemDeploymentCatalog
-> CommittedBarDeploymentSelector
-> CommittedBarOrchestrator
-> StrategyCycleHandoffBoundary(sink=None-by-default)
```

`I4d` is a pure composition change: construct the existing semantic core and
the existing outbound adapters once, attach the semantic core as the
boundary's production sink, add the config inputs the adapters need, and give
the resulting HTTP clients one explicit owner. No orchestration, reconciliation,
or wire-contract decision made in `I3`/`I4a`/`I4b`/`I4c` is reopened here.

## Goals / Non-Goals

**Goals**

- Compose the existing components into exactly the graph fixed by
  `runtime-live-entry-production-integration-plan.md` §6.
- Add the five outbound-service config inputs and a fail-closed readiness rule
  for them, reusing each adapter's own URL/timeout validation rather than
  duplicating it.
- Give the four HTTP clients one explicit constructor/owner with a
  deterministic shutdown and partial-construction-failure cleanup.
- Prove one real vertical background path (webhook → background handoff →
  Engine → ABI → save) with real HTTP-shaped transport on the Runtime side,
  and prove the no-op/cancel/failure branches individually.

**Non-Goals**

- Changing the `http-closed-bar` HTTP contract, status codes, or the
  background-acknowledgement timing. The existing `BackgroundTasks` handoff
  and the existing
  `test_acknowledgement_is_sent_before_background_task_completes` test are
  unchanged.
- Any new orchestration, reconciliation, or outbound wire-contract component.
- Durable persistence, a queue/broker/worker framework, retry, replay, or
  deduplication.
- The ABI fill webhook, `AbiExecutionEventOrchestrator`, or open-trade
  application (`I5`/`I6`/open-trade gate).
- Engine, ABI, or MDS contract changes.

## 1. Existing vs. target composition graph

**Existing (today):**

```text
POST /v1/webhooks/closed-bar
-> ClosedBarRequest validation, readiness check
-> BackgroundTasks.add_task(process_committed_bar)
-> HTTP 200 {"status":"accepted"}
   ...(async, outside the HTTP response cycle)...
-> CommittedBarOrchestrator.process
    -> FilesystemDeploymentCatalog.load_snapshot
    -> CommittedBarDeploymentSelector.select
    -> per selected deployment: StrategyCycleHandoffBoundary.dispatch(unit)
        -> sink(unit) if attached, else no-op success
    -> JsonlProcessingJournal
```

In production, no sink is attached: the semantic core is fully implemented but
unreachable from the webhook.

**Target (`I4d`):**

```text
POST /v1/webhooks/closed-bar                              [unchanged]
-> ClosedBarRequest validation, readiness check            [unchanged]
-> BackgroundTasks.add_task(process_committed_bar)         [unchanged]
-> HTTP 200 {"status":"accepted"}                          [unchanged]
   ...(async)...
-> CommittedBarOrchestrator.process                        [unchanged]
    -> FilesystemDeploymentCatalog.load_snapshot            [unchanged]
    -> CommittedBarDeploymentSelector.select                [unchanged]
    -> per selected deployment: StrategyCycleHandoffBoundary.dispatch(unit)
        -> StrategyRuntimeOrchestrator.process(unit)        [NEW production sink]
            -> keyed_mutex_registry.hold(strategy_instance_id)      [shared]
            -> state_repository.get_or_create(...)                  [shared]
            -> OpenPositionResolver.resolve(state)
                -> HttpxAbiOpenPositionLookupAdapter.lookup(...)     [shared client]
            -> StrategyUseCaseRouter.route(...)
                -> position_open=False
                   -> HttpxStrategyEngineLiveEntryAdapter.project_live_entry(...)  [shared client]
                -> position_open=True
                   -> HttpxStrategyEngineOpenTradeAdapter.project_open_trade(...)  [shared client]
            -> LiveEntryProjectedStrategyInstance
                -> EntryReconciliationOrchestrator.execute(projection)
                    -> AbiEntryPackageExecutionBridge.execute(command, source_state)
                        -> HttpxAbiEntryPackageAdapter.send(...)     [shared client]
            -> state_repository.save(resulting_state)   [only if resulting_state != source_state]
    -> JsonlProcessingJournal                                [unchanged]
```

Only the sink attached to `StrategyCycleHandoffBoundary` changes; every stage
above it (HTTP boundary, `CommittedBarOrchestrator`, deployment catalog/
selector, processing journal) is byte-for-byte the existing implementation.

## 2. Construction ownership

`build_application` becomes the single composition root for the entire graph
above. It constructs, in dependency order:

1. The existing utility contour (unchanged construction).
2. Five outbound HTTP clients (four owned adapter instances; see §6 for the
   exact set) from the new config fields.
3. `OpenPositionResolver(abi_lookup=<open-position adapter>)`.
4. `StrategyUseCaseRouter(live_entry_engine=<...>, open_trade_engine=<...>)`.
5. `AbiEntryPackageExecutionBridge(abi_entry_package=<entry-package client>)`.
6. One `InMemoryStrategyInstanceRuntimeStateRepository()`.
7. One `StrategyInstanceKeyedMutexRegistry()`.
8. `EntryReconciliationOrchestrator(trade_cycle_id_factory=new_trade_cycle_id, execution_port=<bridge>)`.
9. `StrategyRuntimeOrchestrator(state_repository=<6>, open_position_resolver=<3>, use_case_router=<4>, keyed_mutex_registry=<7>, entry_reconciliation_orchestrator=<8>)`.
10. `StrategyCycleHandoffBoundary(sink=<9>.process)` — or `.dispatch`; see the
    open note in §"Sink signature" below.

No step above introduces a new class; every constructor signature already
exists on `main`. `I4d` only adds the call sites and the config plumbing that
feeds them.

**Sink signature note.** `StrategyCycleHandoffSink[DeploymentT]` is
`Callable[[StrategyBarProcessingUnit[DeploymentT]], None]` — it discards the
return value. `StrategyRuntimeOrchestrator.process` returns
`StrategyInstanceRuntimeState`, so the production sink is a thin closure
`lambda unit: orchestrator.process(unit)` (discarding the result) rather than
`.process` passed directly as the sink; `orchestrator.dispatch` already has the
matching `-> StrategyCycleDispatchOutcome`-free... no — `dispatch` returns
`StrategyCycleDispatchOutcome`, also non-`None`. Either way the sink callable
must discard whatever `process`/`dispatch` returns. Tasks §6 decides the exact
one-line adapter; both `process` and `dispatch` call the identical critical
section, so the choice is a wiring detail, not a behavioral one — `dispatch`
already exists specifically to satisfy this exact port shape (it wraps
`process` and returns a discardable outcome), so it is the natural choice
unless implementation finds a reason to prefer the bare closure over `process`.

## 3. Background webhook lifecycle

Unchanged. The HTTP handler in `adapters/http/app.py` still: validates the
request, checks `app.state.ready`, registers
`app.state.process_committed_bar` via `BackgroundTasks.add_task`, and returns
`200 {"status":"accepted"}` before that task runs. `I4d` changes only what
`process_committed_bar` is bound to at construction time — today a closure
over `CommittedBarOrchestrator.process` with an unattached handoff sink;
after `I4d`, the same closure, but the handoff sink is now the composed
`StrategyRuntimeOrchestrator`. The background task's exception-swallowing
behavior (`test_background_failure_does_not_change_acknowledgement`) is
unchanged: `CommittedBarOrchestrator.process` already isolates and journals a
per-unit dispatch failure without raising past its own boundary, and
`process_committed_bar` still runs as a fire-and-forget `BackgroundTasks`
callback.

## 4. MDS acknowledgement vs. ABI acknowledgement

Two distinct, non-interchangeable confirmation boundaries exist in the target
graph, and neither this change nor any future one may collapse them:

| | MDS webhook acknowledgement | ABI entry-package acknowledgement |
|---|---|---|
| Signal | `HTTP 200 {"status":"accepted"}` | `EntryPackageApplied` / `EntryPackageAbsent` |
| Meaning | The webhook body validated and a background committed-bar cycle was registered | The desired attached entry package (or its absence) is now ABI's acknowledged state for this trade cycle |
| Timing | Sent before any downstream work starts | Received strictly inside the held keyed mutex, after Engine projection |
| Authorizes | Nothing beyond "accepted for background processing" | The only event that authorizes `EntryReconciliationOrchestrator` to apply a reconciliation result and `StrategyRuntimeOrchestrator` to call repository `save(...)` |
| Failure after this point | N/A — it is the terminal signal to MDS | Recorded via the existing processing-journal/outcome mechanism; no HTTP response exists to change |

`200 {"status":"accepted"}` never asserts that Strategy Engine projected
successfully, that ABI acknowledged an entry package, that Runtime state was
saved, or that an order was placed, amended, or filled — this is the existing
`http-closed-bar` contract (`Scenario: Acceptance does not imply trading
success`) and remains true unchanged: the composed background path can fail
at any of its three outbound boundaries, or succeed as `NO_OP`, without any
observable difference at the HTTP layer.

## 5. Repository and mutex identity

`build_application` constructs exactly one
`InMemoryStrategyInstanceRuntimeStateRepository` and exactly one
`StrategyInstanceKeyedMutexRegistry` per application instance, and passes the
same two objects into the single `StrategyRuntimeOrchestrator`. No other
constructor in the graph receives its own instance of either. This change does
not yet expose either instance for `I5` to reuse (no fill webhook exists yet),
but composition must not make sharing structurally impossible: both instances
should be reachable from the composition root (e.g., held as local variables
returned alongside the app, or attached to application state) so a future `I5`
change can pass the same instances into `AbiExecutionEventOrchestrator` without
restructuring `build_application`. Guardrail tests assert `is`-identity, not a
construction call count, since a call-count assertion cannot detect two
separately constructed-but-equal instances.

## 6. HTTP client startup/shutdown lifecycle

Four owned clients: `HttpxStrategyEngineLiveEntryAdapter`,
`HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`, and
the existing `HttpxAbiEntryPackageAdapter`. All four already implement
`close()` and the `__enter__`/`__exit__` context-manager protocol.

Contracted lifecycle (implementation-agnostic — the exact FastAPI wiring
mechanism, e.g. a `lifespan` context manager vs. an equivalent, is an
implementation choice `tasks.md` resolves, not a decision this design pins):

- Each of the four clients is constructed exactly once, during
  `build_application`, after config validation succeeds.
- The same four instances are reused for every background committed-bar cycle
  and every strategy instance for the lifetime of the application; no adapter
  is constructed per request or per cycle.
- On application shutdown, each of the four owned clients is closed exactly
  once. Closing is idempotent per client (`close()` may safely be the only
  call), and the composition root is the only code path that calls it — no
  adapter closes itself, and no per-request code path closes a shared client.
- If constructing the graph fails partway (e.g., the Engine clients succeed
  but the ABI base URL is invalid), every client already constructed before
  the failure is closed before `build_application` returns the not-ready
  application; no client is leaked because a later step in construction failed.
- Invalid or missing production config never reaches partial graph
  construction: config is loaded and validated before any HTTP client is
  constructed, exactly as journal/specs-path preparation already precedes
  catalog construction today.

## 7. Config and readiness

| Variable | Type | Rule | Consumed by |
|---|---|---|---|
| `RUNTIME_STRATEGY_ENGINE_BASE_URL` | str | absolute `http`/`https` URL | both Strategy Engine adapters |
| `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS` | float | finite, `> 0` | both Strategy Engine adapters |
| `RUNTIME_ABI_BASE_URL` | str | absolute `http`/`https` URL | ABI open-position adapter and ABI entry-package client |
| `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS` | float | finite, `> 0` | ABI open-position adapter only |
| `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` | float | finite, `> 0` | ABI entry-package client only |

One `RUNTIME_ABI_BASE_URL` is shared by two independently timed-out ABI
adapters; there is no separate base URL per ABI endpoint. URL scheme/host and
timeout finiteness/positivity are already enforced inside each adapter's own
constructor (`HttpxStrategyEngineLiveEntryAdapter`/`...OpenTradeAdapter`
`_build_client`, `HttpxAbiOpenPositionLookupAdapter.__init__`,
`HttpxAbiEntryPackageAdapter.__init__` all raise `ValueError`/`TypeError` for
an invalid URL or non-finite/non-positive timeout) — `load_runtime_config`
only needs to parse the timeout strings into `float` and pass every field
through; it does not need to duplicate URL-shape or timeout-sign validation,
mirroring how `RUNTIME_PORT` parsing already delegates its range check to
`RuntimeConfig.__post_init__` rather than duplicating it in the loader.

Readiness stays exactly the existing fail-closed pattern in
`build_application`: config loading, journal/specs preparation, and now the
five new fields plus adapter construction all happen inside the same
`try/except Exception` block that already exists; any failure — a missing
variable, an unparsable timeout, an invalid URL, or an adapter constructor
`ValueError` — produces `ready=False` via the existing
`create_http_app(ready=False, ...)` branch. No new retry, circuit breaker, or
speculative-policy field is introduced.

## 8. Background success sequence (happy path)

```text
1. position_open=False (ABI open-position lookup)
2. Engine live-entry returns a non-null desired_entry
3. EntryReconciliationOrchestrator decides APPLY (no existing acknowledged package)
4. AbiEntryPackageExecutionBridge reads risk_multiplier only from source_state
5. AbiEntryPackagePort.send returns EntryPackageApplied
6. EntryReconciliationOrchestrator returns a replacement StrategyInstanceRuntimeState
   with a new CurrentTradeCycle
7. StrategyRuntimeOrchestrator saves the replacement state (value-different from source)
```

## 9. Background failure table

| Failure point | Downstream effect | Repository save? | HTTP response |
|---|---|---|---|
| ABI open-position lookup fails (timeout/network/protocol/public error) | Engine is never called | No | Unaffected — already sent as `200 accepted` |
| Strategy Engine projection fails | ABI entry-package is never called | No | Unaffected |
| `desired_entry=null`, no current cycle | `NO_OP` decided | No | Unaffected |
| `desired_entry=null`, acknowledged current cycle | `CANCEL` decided; requires `EntryPackageAbsent` | Only after confirmed `EntryPackageAbsent`; cycle is cleared, not left partially cancelled | Unaffected |
| ABI entry-package call fails (public/transport/protocol) | `EntryReconciliationExecutionError` raised | No — the prior aggregate is returned unchanged by `StrategyRuntimeOrchestrator`'s existing exception propagation | Unaffected |
| `position_open=True` | Engine open-trade adapter may be called (it exists and is wired) | No — `StrategyRuntimeOrchestrator` still raises `OpenTradeProjectionUnsupportedError`; open-trade application remains unimplemented | Unaffected |
| Any of the above | Recorded by `CommittedBarOrchestrator`'s existing per-unit exception handling as a failed `StrategyCycleDispatchOutcome`, journaled by the existing `JsonlProcessingJournal` | — | Unaffected |

Every row reuses existing, already-tested exception types and existing
`StrategyRuntimeOrchestrator`/`EntryReconciliationOrchestrator` propagation
behavior (see the archived `strategy-runtime-orchestrator` spec, "Closed-bar
semantic errors propagate without recovery"); `I4d` adds no new failure type.

## 10. State-save rules

Unchanged from the existing `StrategyRuntimeOrchestrator` implementation and
its archived spec: repository `save(...)` is called at most once per
background cycle, only when
`EntryReconciliationOrchestrator.execute(...)` returns a
`StrategyInstanceRuntimeState` that is value-different from
`projection.source.resolved_state.runtime_state`; a logically unchanged
(`NO_OP`) result performs zero saves. `I4d` composes this rule into production
without altering it — no new save path, partial-field save, or optimistic
save-before-confirmation is introduced anywhere in the composition root.

## 11. Known non-durable Live V1 limitation

The in-memory repository is the selected implementation for `I4d`, not a
placeholder pending completion in this change:

```text
In-memory repository is the selected implementation for I4d.
Process-restart durability remains a future architecture gate.
```

Accepted limitation, not an open task of this change:

```text
Runtime may acknowledge a webhook (200 accepted) and then terminate before
its in-process background task completes. The in-flight committed-bar cycle
is lost; no persisted pending action, replay, or recovery mechanism exists in
Live V1. This matches the already-accepted Live V1 concurrency model
(runtime-master-plan.md §9, runtime-state-and-lifecycle-plan.md §10): a
single process, single worker, no restart recovery, no durable pending-action
log.
```

`infrastructure/runtime_state/sqlite_repository.py` remains the existing empty
placeholder; `I4d` does not implement it, and does not add a queue, broker,
worker framework, retry, replay, or deduplication mechanism.

## 12. Rejected alternatives

**Synchronous HTTP processing.** Replacing `BackgroundTasks` with an in-request
synchronous call to the full composed graph was considered so the HTTP
response could reflect a confirmed outcome. Rejected: it would change the
ratified `http-closed-bar` contract (`Scenario: Return before background work
completes`) and invalidate the existing
`test_acknowledgement_is_sent_before_background_task_completes` test, which
this change is explicitly scoped to leave unchanged. The existing contract
already documents that acceptance does not imply trading success, so there is
no fail-closed requirement this change needs synchronous processing to satisfy
— fail-closed is enforced inside the critical section (§9, §10), not at the
HTTP layer.

**A new durable queue/broker between the webhook and the semantic core.**
Rejected: not required by `I4d`'s scope, adds a new failure mode and
operational dependency, and the accepted Live V1 concurrency model
(single process, single worker, non-durable in-memory state) already accepts
the equivalent risk for repository state; introducing durable delivery for the
webhook handoff alone would create an inconsistent durability boundary without
closing the larger gap.

**Implementing `infrastructure/runtime_state/sqlite_repository.py` in this
change.** Rejected: durable persistence is an explicit future architecture
gate (`runtime-master-plan.md` §10.1), out of scope for `I4c`/`I4d`, and doing
it here would silently expand this change from composition-only to a new
persistence design.

**A new top-level semantic orchestrator or projection coordinator.** Rejected:
`StrategyRuntimeOrchestrator` already owns the complete keyed critical section
end to end (`I4b`, archived); introducing another coordinator above or beside
it would duplicate mutex/repository ownership and contradict the already
-accepted "one coordinator" decision in `runtime-abi-entry-reconciliation-master-plan.md`
§3.

**Constructing HTTP clients per request or per background cycle.** Rejected:
the four adapters already support long-lived construction (persistent
`httpx.Client`, connection pooling); per-request construction would add
latency, defeat connection reuse, and complicate the shutdown-ownership
contract in §6 by scattering client lifetimes across every request instead of
the application lifetime.

## Explicit I5/I6 gates

- `I5` (ABI fill webhook, `AbiExecutionEventOrchestrator`) starts only after
  this change is verified and archived, and must reuse the exact repository
  and keyed-mutex-registry instances this change constructs — it must not
  construct a second instance of either.
- `I6` (entry/fill cross-flow guardrails) and the open-trade
  requirements/implementation gate remain fully out of scope; this change
  keeps `OpenTradeProjectionUnsupportedError` as the only observable behavior
  for `position_open=True`, even though the open-trade Engine adapter is now
  reachable and may be called by `StrategyUseCaseRouter` as part of routing.

## Risks / Trade-offs

- Holding the keyed mutex across three real outbound HTTP calls (open-position
  lookup, Engine projection, ABI entry-package call) means a slow or hung
  outbound dependency now measurably delays same-instance background cycles in
  production, not just in tests. This is the already-accepted Live V1 trade-off
  (`runtime-master-plan.md` §9); `I4d` makes it observable in production for
  the first time but does not change the bound (each call already carries its
  own bounded, non-retried timeout).
- A process restart between HTTP acknowledgement and background-task
  completion silently drops that cycle (see §11). This is accepted for Live V1
  and not remediated by this change.

## Migration Plan

No data migration. This is an additive composition and config change;
existing deployments without the five new environment variables move from
`ready=True` (utility-only) to `ready=False` (composition requires them) upon
upgrade, which is the intended fail-closed behavior — operators must supply
the five variables before the upgraded Runtime becomes ready.

## Open Questions

None outstanding. The acknowledgement-semantics, durability, capability-split,
and composition-ownership decisions in this document were fixed by the
architectural pre-pass review before this change was written; no unresolved
discrepancy between the authoritative system plans and the current code
remains after those decisions.
