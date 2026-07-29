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
boundary's one and only production sink, add the config inputs the adapters
need, and give the resulting HTTP clients one explicit owner. No orchestration,
reconciliation, or wire-contract decision made in `I3`/`I4a`/`I4b`/`I4c` is
reopened here.

`build_application` becomes the single production composition root with
exactly one ready construction path. It no longer accepts a caller-supplied
`strategy_cycle_handoff` override: a `ready=True` result always means the
complete graph below was constructed. This is a deliberate closure of a
structural ambiguity: an earlier draft of this design kept a "test override"
construction mode that could return `ready=True` with only the utility contour
and no semantic graph at all. That second, structurally different path is
removed entirely — not replaced by another injection parameter, environment
flag, or "utility mode" — because it re-opened exactly the kind of
default-vs-override composition ambiguity this change exists to close (see
"Rejected alternatives" below).

## Goals / Non-Goals

**Goals**

- Compose the existing components into exactly the graph fixed by
  `runtime-live-entry-production-integration-plan.md` §6.
- Add the five outbound-service config inputs and a fail-closed readiness rule
  for them, reusing each adapter's own URL/timeout validation rather than
  duplicating it.
- Give the four HTTP clients one explicit constructor/owner with a
  deterministic shutdown and startup-rollback cleanup.
- Prove one real vertical background path (webhook → background handoff →
  Engine → ABI → save) with real HTTP-shaped transport on the Runtime side,
  and prove the no-op/cancel/failure branches individually.
- Make `build_application` a single-path composition root: every `ready=True`
  result has the complete graph, with no alternative utility-only ready
  result and no caller-supplied composition override.

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
- Preserving any caller-supplied composition override in
  `build_application` — this is explicitly removed, not preserved (§2a).

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
        -> process_strategy_cycle(unit)                     [NEW, unconditional, thin sink]
            -> StrategyRuntimeOrchestrator.process(unit)
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

Only the sink attached to `StrategyCycleHandoffBoundary` changes, and it
changes unconditionally — there is no branch of `build_application` that skips
this graph. Every stage above it (HTTP boundary, `CommittedBarOrchestrator`,
deployment catalog/selector, processing journal) is byte-for-byte the existing
implementation.

## 2. Construction ownership

`build_application` becomes the single composition root for the entire graph
above, with exactly one ready construction path (no parameter selects a
different one). It constructs, in dependency order:

1. The existing utility contour (unchanged construction).
2. Four outbound HTTP clients (one per adapter instance; see §6 for the exact
   set) from the new config fields.
3. `OpenPositionResolver(abi_lookup=<open-position adapter>)`.
4. `StrategyUseCaseRouter(live_entry_engine=<...>, open_trade_engine=<...>)`.
5. `AbiEntryPackageExecutionBridge(abi_entry_package=<entry-package client>)`.
6. One `InMemoryStrategyInstanceRuntimeStateRepository()`.
7. One `StrategyInstanceKeyedMutexRegistry()`.
8. `EntryReconciliationOrchestrator(trade_cycle_id_factory=new_trade_cycle_id, execution_port=<bridge>)`.
9. `StrategyRuntimeOrchestrator(state_repository=<6>, open_position_resolver=<3>, use_case_router=<4>, keyed_mutex_registry=<7>, entry_reconciliation_orchestrator=<8>)`.
10. The thin, `None`-returning sink function wrapping `<9>.process(unit)` (see
    the closed "Sink signature" decision below), passed as
    `StrategyCycleHandoffBoundary(sink=process_strategy_cycle)`.

No step above introduces a new class; every constructor signature already
exists on `main`. `I4d` only adds the call sites and the config plumbing that
feeds them.

**Sink signature (closed).** `StrategyCycleHandoffSink[DeploymentT]` is
`Callable[[StrategyBarProcessingUnit[DeploymentT]], None]`: it must return
`None`. Neither `StrategyRuntimeOrchestrator.process` (returns
`StrategyInstanceRuntimeState`) nor `.dispatch` (returns
`StrategyCycleDispatchOutcome`) satisfies that signature directly, and
`StrategyCycleHandoffBoundary` itself already builds the final
`StrategyCycleDispatchOutcome` that `CommittedBarOrchestrator` consumes — using
`.dispatch` as the sink would construct a second, inner
`StrategyCycleDispatchOutcome` that is immediately discarded by the boundary,
for no behavioral benefit. The production sink is therefore a thin,
`None`-returning function that calls `.process` and discards its return value:

```python
def process_strategy_cycle(
    unit: StrategyBarProcessingUnit[DeploymentSpecification],
) -> None:
    strategy_runtime_orchestrator.process(unit)
```

This is a wiring detail, not a new component: it introduces no class, and
neither `StrategyRuntimeOrchestrator.process` nor `.dispatch` changes
signature. `.dispatch` remains available for any caller that wants a
`StrategyCycleDispatchOutcome` directly (none does, in this graph);
`StrategyCycleHandoffBoundary` is that caller for `CommittedBarOrchestrator`,
and it calls the thin sink, not `.dispatch`, to avoid the redundant nested
outcome above. This sink is the *only* sink `build_application` ever attaches
— unconditionally, for every call, since no override parameter exists (§2a).

## 2a. Single ready construction path (no caller override)

`build_application`'s public signature no longer declares a
`strategy_cycle_handoff` parameter. There is exactly one construction path:

```text
build_application(...)
-> load complete production config (five outbound fields + existing fields)
-> construct the complete Runtime graph (§2 steps 1-9)
-> attach the thin process_strategy_cycle sink (§2 step 10)
-> return ready=True
```

or, on any config or construction failure, the not-ready application (§6, §7).
There is no second path, mode, flag, or parameter that returns `ready=True`
with only the utility contour and no semantic graph. Concretely:

- the five outbound config fields are required for every `ready=True` result,
  with no exception;
- the complete semantic graph and all four outbound HTTP clients are
  constructed for every `ready=True` result, with no exception;
- `build_application` accepts no parameter that lets a caller replace
  `process_strategy_cycle` with a different sink, skip constructing the
  semantic graph, or skip constructing the four outbound HTTP clients.

**Consequence for utility-contour testing.** The existing
`tests/integration/committed_bar/test_production_composition.py` test
previously exercised the utility contour in isolation by calling
`build_application(..., strategy_cycle_handoff=received.append)` with only
utility-only configuration. That call shape no longer compiles/type-checks
against the new signature and would no longer return `ready=True` if it did
(the five outbound fields would be missing). This is an intended, accepted
consequence, not an oversight: `build_application` is a production composition
root, not a utility-contour test harness. The utility contour's own isolated
testability does not depend on `build_application` at all — it is fully
exercised by constructing `FilesystemDeploymentCatalog`,
`CommittedBarDeploymentSelector`, `JsonlProcessingJournal`, and
`StrategyCycleHandoffBoundary` directly (tasks.md §6 requires this rewrite as
part of implementation, not as a follow-up).

## 3. Background webhook lifecycle

Unchanged. The HTTP handler in `adapters/http/app.py` still: validates the
request, checks `app.state.ready`, registers
`app.state.process_committed_bar` via `BackgroundTasks.add_task`, and returns
`200 {"status":"accepted"}` before that task runs. `I4d` changes only what
`process_committed_bar` is bound to at construction time — today a closure
over `CommittedBarOrchestrator.process` with an unattached handoff sink;
after `I4d`, the same closure, but the handoff sink is now, unconditionally,
the thin wrapper over the composed `StrategyRuntimeOrchestrator`. The
background task's exception-swallowing behavior
(`test_background_failure_does_not_change_acknowledgement`) is unchanged:
`CommittedBarOrchestrator.process` already isolates and journals a per-unit
dispatch failure without raising past its own boundary, and
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
should be reachable from the composition-owned application bundle/state that
`build_application` returns (e.g., held as local variables returned alongside
the app, or attached to application state) so a future `I5` change can pass the
same instances into `AbiExecutionEventOrchestrator` without restructuring
`build_application` and without introducing an alternative build mode or
parameter to expose them. Guardrail tests assert `is`-identity, not a
construction call count, since a call-count assertion cannot detect two
separately constructed-but-equal instances.

## 6. HTTP client startup/shutdown lifecycle

Four owned clients: `HttpxStrategyEngineLiveEntryAdapter`,
`HttpxStrategyEngineOpenTradeAdapter`, `HttpxAbiOpenPositionLookupAdapter`, and
the existing `HttpxAbiEntryPackageAdapter`. All four already implement
`close()` and the `__enter__`/`__exit__` context-manager protocol.

No new semantic orchestrator, reconciliation component, domain service, or
outbound adapter class is introduced by this lifecycle requirement. A small
composition-root lifecycle owner — a plain object or closure bundling the four
client references and one close-all operation — is allowed and is the
expected shape of the "single explicit owner" below; it is a lifecycle
convenience, not a new architectural layer. The exact FastAPI wiring mechanism
(a `lifespan` context manager vs. an equivalent) is left to `tasks.md`, not
pinned by this design.

One composition lifecycle owner performs exactly two allowed close
operations across the application's life — **startup rollback** and
**application shutdown** — and no other code path ever calls `close()` on any
of the four clients: not an HTTP request handler, not a background
committed-bar cycle, not `StrategyRuntimeOrchestrator`, `OpenPositionResolver`,
`StrategyUseCaseRouter`, `EntryReconciliationOrchestrator`, an outbound adapter
after an individual call, or any other caller.

### Successful ready construction

```text
four clients constructed once
-> reused for every background committed-bar cycle, for the application's life
-> each closed exactly once, by the lifecycle owner, on application shutdown
```

### Failed partial construction (startup rollback)

```text
some clients constructed
-> a later client's constructor rejects its configuration
-> every already-constructed client is closed exactly once, by the lifecycle
   owner, during startup rollback -- not shutdown, since no ready application
   exists yet
-> those clients are never exposed in a returned application
-> they are not closed again later (rollback already closed them)
-> build_application returns the not-ready application
```

Construction happens in the deterministic order fixed by §2. Two distinct
config-failure stages exist and must not be conflated (§7 has the exact field
-by-field boundary):

- **Before any client is constructed** (config loading/parsing): a missing
  required variable, or a timeout string that cannot parse to `float`, is
  discovered here — before any HTTP client exists. Zero clients are
  constructed; there is nothing for startup rollback to close.
- **During client construction** (adapter constructor validation): a value
  that parsed successfully but is semantically invalid — a
  malformed/non-absolute/non-HTTP(S) URL, a `NaN`/infinite timeout, or a
  zero/negative timeout — is discovered only when an adapter constructor
  runs. One or more earlier clients in the deterministic order may already
  exist at that point; startup rollback closes each of them exactly once.

Either stage ends the same way: `build_application` returns the not-ready
application, and no partially usable production graph is ever returned as
`ready=True`.

## 7. Config and readiness

| Variable | Type | Rule | Consumed by |
|---|---|---|---|
| `RUNTIME_STRATEGY_ENGINE_BASE_URL` | str | absolute `http`/`https` URL | both Strategy Engine adapters |
| `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS` | float | finite, `> 0` | both Strategy Engine adapters |
| `RUNTIME_ABI_BASE_URL` | str | absolute `http`/`https` URL | ABI open-position adapter and ABI entry-package client |
| `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS` | float | finite, `> 0` | ABI open-position adapter only |
| `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS` | float | finite, `> 0` | ABI entry-package client only |

These five fields are unconditionally required for any `ready=True` result of
`build_application` — there is no construction path that omits them (§2a).

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
`try/except Exception` block that already exists. Two distinct failure stages
exist (§6) and must be kept distinct in implementation and tests: a missing
variable or an unparsable timeout string is discovered during config
loading/parsing, before any HTTP client is constructed — this can never be
discovered for the first time by a late adapter constructor, since parsing
happens first. A malformed URL, a non-finite/non-positive timeout, or another
adapter-constructor rejection is discovered only during client construction,
after zero or more earlier clients already exist. Either stage produces
`ready=False` via the existing `create_http_app(ready=False, ...)` branch,
closing any client already constructed via startup rollback (§6). No new
retry, circuit breaker, or speculative-policy field is introduced.

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
| ABI entry-package call fails (public/transport/protocol) | `EntryReconciliationExecutionError` raised, propagating out of `EntryReconciliationOrchestrator` and `StrategyRuntimeOrchestrator` | No — repository retains the prior aggregate; no save is attempted | Unaffected |
| `position_open=True` | Engine open-trade adapter may be called (it exists and is wired); `StrategyRuntimeOrchestrator` raises `OpenTradeProjectionUnsupportedError`, propagating the same way | No — open-trade application remains unimplemented | Unaffected |
| Any of the above | Recorded by `CommittedBarOrchestrator`'s existing per-unit exception handling as a failed `StrategyCycleDispatchOutcome`, journaled by the existing `JsonlProcessingJournal` | — | Unaffected |

Every row reuses existing, already-tested exception types and existing
`StrategyRuntimeOrchestrator`/`EntryReconciliationOrchestrator` propagation
behavior (see the archived `strategy-runtime-orchestrator` spec, "Closed-bar
semantic errors propagate without recovery"); `I4d` adds no new failure type.

**Propagation rule (applies to every row above).** Every failure or explicit
error above is raised out of `EntryReconciliationOrchestrator` and/or
`StrategyRuntimeOrchestrator.process` uncaught by the semantic core.
`StrategyCycleHandoffBoundary` does not catch it either — it does not
fabricate a successful `StrategyCycleDispatchOutcome` internally. The
exception reaches its existing catch point in
`CommittedBarOrchestrator.process`, which converts it into the existing
failed `StrategyCycleDispatchOutcome` and journals it via
`JsonlProcessingJournal`, exactly as it already does today for any dispatcher
exception. The observable production result of a background failure is
therefore: a failed-dispatch journal record, a repository holding no new save
for that cycle, and no downstream call that depended on the failed one — not
a raised exception surfacing out of the HTTP/background boundary itself. Test
coverage (tasks §8) verifies both layers: the uncaught propagation at the
component level (out of `EntryReconciliationOrchestrator`/
`StrategyRuntimeOrchestrator`), and the journaled/observable outcome at the
full `TestClient`/background-contour level.

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

**A caller-supplied composition override (`strategy_cycle_handoff` parameter)
carried forward from the pre-`I4d` bootstrap.** Rejected, after being tried in
an earlier draft of this design. Keeping a parameter that lets a caller
replace the production sink — and thereby skip constructing the semantic graph
and the four outbound HTTP clients — creates a second, structurally different
`ready=True` result alongside the production graph. That is exactly the
composition ambiguity this change exists to close: "is `ready=True` always the
complete graph?" must have one unconditional answer. The override is removed
outright, not replaced by another injection parameter, environment flag, or
"utility mode" — the utility contour's isolated testability is preserved by
testing its components directly (§2a), which needs no override in
`build_application` at all.

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
  and keyed-mutex-registry instances this change constructs, reached through
  the composition-owned application bundle/state that `build_application`
  returns — it must not construct a second instance of either, and must not
  reintroduce an alternative build mode or override parameter to obtain them.
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
- Removing `build_application`'s `strategy_cycle_handoff` parameter is a
  breaking change to that function's call sites, including the existing
  utility-contour test. This is an intended, one-time migration cost (tasks.md
  §6), not an ongoing risk.

## Migration Plan

No data migration. This is an additive composition/config change plus one
breaking signature change:

- Existing deployments without the five new environment variables move from
  `ready=True` to `ready=False` upon upgrade, which is the intended
  fail-closed behavior — operators must supply the five variables before the
  upgraded Runtime becomes ready.
- Any call site (test or otherwise) passing `strategy_cycle_handoff=...` to
  `build_application` must be updated: production code has none today; the
  only known call site is the utility-contour test, which is rewritten to
  construct utility components directly instead (tasks.md §6).

## Open Questions

None outstanding. The single-construction-path decision, the acknowledgement
-semantics, durability, capability-split, and composition-ownership decisions
in this document were fixed by the architectural pre-pass review before this
change was written; no unresolved discrepancy between the authoritative
system plans and the current code remains after those decisions.
