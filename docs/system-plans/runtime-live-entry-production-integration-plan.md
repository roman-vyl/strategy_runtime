# Runtime live-entry production integration plan

Status: architectural source of truth for `I4c` and `I4d`. Both are the same
production adapter and composition integration seam that
[`runtime-master-plan.md`](runtime-master-plan.md) and
[`runtime-abi-entry-reconciliation-master-plan.md`](runtime-abi-entry-reconciliation-master-plan.md)
already required between closed-bar orchestration and the ABI fill webhook.
This document formalizes that seam with concrete wire contracts and a change
split; it does not introduce a new architectural direction.

## 1. Purpose and stopping point

`EntryReconciliationOrchestrator` (I4a) and the closed-bar
`StrategyRuntimeOrchestrator` critical section (I4b) are implemented, tested,
and archived. `StrategyRuntimeOrchestrator.process(unit)` owns the complete
keyed critical section and returns the final `StrategyInstanceRuntimeState`.
None of this is reachable from the production bootstrap: `build_application`
composes only the utility contour and stops at an optional
`StrategyCycleHandoffSink`. Of the five application ports involved
(`StrategyEngineLiveEntryPort`, `StrategyEngineOpenTradePort`,
`AbiOpenPositionLookupPort`, `EntryReconciliationExecutionPort`,
`AbiEntryPackagePort`), four are exercised only through fakes in tests; the
fifth, `AbiEntryPackagePort`, already has a real, contract-tested HTTP
implementation (`abi-entry-package-client-v1`) that is simply not composed
into the application yet.

This plan covers exactly two increments:

- `I4c` — implement and contract-test three new production HTTP adapters
  (`StrategyEngineLiveEntryPort`, `StrategyEngineOpenTradePort`,
  `AbiOpenPositionLookupPort`) and one new application bridge
  (`EntryReconciliationExecutionPort` → the existing `AbiEntryPackagePort`
  client), in isolation. The existing `AbiEntryPackagePort` HTTP client is not
  rewritten; `I4c` only removes its `accepted_risk_multiplier` response echo
  (§3.1).
- `I4d` — wire those adapters, the semantic core, and configuration into one
  production composition root, and prove the live-entry vertical slice with a
  real HTTP-shaped E2E test.

It stops before the ABI fill webhook and `AbiExecutionEventOrchestrator` (I5),
before open-trade/position-management reconciliation, and before any
production-hardening mechanism (durable persistence, CAS, command
idempotency, restart recovery, multi-worker deployment) already deferred by
the master plan.

## 2. Accepted Strategy Engine contracts

The Strategy Engine HTTP contract is treated as settled; no further
architectural discussion is required before writing the adapter against it:

```text
POST /v1/strategy-evaluations/live-entry
POST /v1/strategy-evaluations/open-trade
```

Accepted properties:

- closed request DTOs matching `LiveEntryProjectionRequest` /
  `OpenTradeProjectionRequest`;
- a singular `desired_entry: DesiredEntry | null` in the live-entry response,
  matching `LiveEntryProjectionResponse`;
- an open-trade response carrying only `desired_protection`, `close_signal`,
  and `diagnostics`, matching `OpenTradeProjectionResponse`;
- strict rejection of the obsolete echo-bearing shape (`strategy_instance_id`,
  `trade_id`, market/timeframe/target-bar echoes, hashes, version fields);
- exact-decimal text for all prices;
- a distinguishable `market_stream_not_found` condition;
- a typed HTTP error envelope for validation and internal failures.

Exact live-entry request:

```json
{
  "strategy_id": "...",
  "raw_spec": {},
  "ticker": "BTCUSDT.P",
  "base_timeframe": "5m",
  "target_bar_open_time_ms": 1720000000000
}
```

Exact live-entry response — either an absent desire or a singular
`DesiredEntry`:

```json
{
  "desired_entry": null
}
```

The Runtime-side `OpenTradeProjectionRequest` port model (`strategy_id`,
`raw_spec`, `ticker`, `base_timeframe`, `target_bar_open_time_ms`,
`desired_entry`, `entry_bar_open_time_ms`) maps to this exact Engine wire
request:

```text
strategy_id
raw_spec
ticker
base_timeframe
target_bar_open_time_ms
executed_trade_receipt
```

`executed_trade_receipt` bundles the frozen entry plan with its execution
timestamp:

```text
side
source_plan_bar_open_time_ms
entry_bar_open_time_ms
planned_entry_price
initial_stop_price
initial_take_price
locked_exit_profile
```

It does **not** contain `executed_entry_price`, `strategy_instance_id`, or
`trade_cycle_id` — consistent with the existing rule that
`executed_entry_price` stays a Runtime/ABI execution fact never sent to
Engine, and that Runtime business identities do not cross the Engine
boundary (`runtime-master-plan.md` §7). The adapter is a pure rename/regroup
of the same fields the port model already carries; it does not require any
new execution fact.

Exact Engine error envelope, used for every non-2xx Engine response:

```json
{
  "error": "validation_failed",
  "message": "...",
  "details": {},
  "request_id": "..."
}
```

`market_stream_not_found` is a distinct typed Engine error surfaced as
`HTTP 404` and decoded into its own error variant, not conflated with generic
validation or internal-error cases.

`I4c` writes the adapter directly against this contract and the existing
`strategy_runtime.runtime.engine.live_entry` / `...open_trade` port
definitions. No new Engine-side design work is in scope here; Engine
repository cleanup plans 24–29 are treated as a satisfied prerequisite (see
`runtime-master-plan.md` §10) and remain a separate external track.

## 3. Required ABI contracts

### 3.1 ABI entry-package (`AbiEntryPackagePort`) — implemented, one field to remove

The transport-free client (`EntryPackageRequest` → `EntryPackageResult`) is
already implemented and archived (`abi-entry-package-client-v1`). One field is
a known mismatch against the master plan:

```text
EntryPackageApplied.accepted_risk_multiplier
```

`runtime-abi-entry-reconciliation-master-plan.md` §4 defines
`risk_multiplier` as an operational value that Runtime sends to ABI one-way;
ABI does not return or reconfirm it. `I4c` removes
`accepted_risk_multiplier` from `EntryPackageApplied` and updates every
caller, test, and OpenAPI-conformance fixture accordingly. This is a DTO
cleanup, not a new design discussion.

### 3.2 ABI open-position lookup (`AbiOpenPositionLookupPort`) — not yet fixed

The Runtime-side port is implemented:

```text
OpenPositionLookupRequest
└── strategy_instance_id

OpenPositionLookupResponse
├── position_open: bool
├── entry_bar_open_time_ms: int | null
└── executed_entry_price: exact-decimal text | null
```

No production wire contract exists yet. `I4c` fixes it as:

```text
GET /v1/strategy-instances/{strategy_instance_id}/open-position
```

Response when no position is open:

```json
{
  "position_open": false,
  "entry_bar_open_time_ms": null,
  "executed_entry_price": null
}
```

Response when a position is open:

```json
{
  "position_open": true,
  "entry_bar_open_time_ms": 1720000000000,
  "executed_entry_price": "61234.5"
}
```

Rule: the absence of an open position for a `strategy_instance_id` is
`HTTP 200` with `position_open=false`, never `HTTP 404`. A newly deployed
strategy instance legitimately has no ABI record yet; that is not an error
condition.

Error semantics:

- `strategy_instance_id` is an opaque external identifier; Runtime does not
  impose its own regex/format validation on it before sending it to ABI;
- a malformed request or path-encoding problem is ABI's own public error,
  surfaced as ABI's future `400`/`422` contract — Runtime decodes it as a
  typed public error, it does not invent the validation rule itself;
- an ABI internal fault or unavailability is `5xx`, decoded as a typed
  internal/unavailable error;
- an unexpected `404` does **not** mean a flat/closed position — it is
  decoded as a typed protocol/public failure, exactly like any other
  unexpected non-2xx response;
- only a successful `200` with `position_open=false` in the body means "no
  open position"; every other outcome (any unexpected non-2xx, malformed
  body, timeout, transport failure) becomes a typed public/protocol/transport
  failure and is never silently coerced into `position_open=false`.

## 4. Runtime outbound adapter responsibilities

`I4c` implements, in isolation, bounded HTTP adapters/bridges behind four of
the five application ports (the fifth, `AbiEntryPackagePort`, already has a
production HTTP client — §3.1):

1. `StrategyEngineLiveEntryPort` → `POST /v1/strategy-evaluations/live-entry`.
2. `StrategyEngineOpenTradePort` → `POST /v1/strategy-evaluations/open-trade`.
   `StrategyUseCaseRouter` requires both ports even though the first
   production E2E only exercises the live-entry path — an open position
   routes through the open-trade port at runtime, so it cannot be left
   unimplemented.
3. `AbiOpenPositionLookupPort` → the open-position endpoint fixed in §3.2.
4. The entry-execution bridge described in §5.

Every adapter:

- uses closed/strict request and response DTOs, rejecting unknown or
  obsolete fields;
- URL-encodes path segments;
- applies a bounded timeout with no retry and no redirect-following;
- decodes into one typed result union: success, typed public/business error,
  transport error, timeout, protocol/decoding error;
- is covered by fake-HTTP contract tests (request shape, success decoding,
  every typed error branch, timeout, malformed response).

## 5. Entry execution adaptation

`EntryReconciliationExecutionPort.execute(command, source_state)` is the
application-side execution boundary already called by
`EntryReconciliationOrchestrator`. `I4c` implements the concrete bridge from
this port to the existing `AbiEntryPackagePort` client:

```text
EntryReconciliationCommand + source_state
→ EntryPackageRequest
   (strategy_instance_id, trade_cycle_id, ticker,
    desired_entry: EntryPackageWireDesiredEntry | None,
    risk_multiplier = source_state.risk_multiplier)
→ AbiEntryPackagePort.send
→ EntryPackageApplied  → SuccessfulEntryConfirmation (EntryAppliedConfirmation)
   EntryPackageAbsent  → SuccessfulEntryConfirmation (EntryAbsentConfirmation)
   EntryPackagePublicError / transport / timeout / protocol
                       → raised as a typed execution failure
```

This bridge does not reimplement reconciliation decisions (`NoOp`/`Apply`/
`Replace`/`Cancel` remain I3), does not acquire the mutex, and does not
reload or save state — it only translates one transport-free command into
one ABI wire call and adapts the wire result back into the closed
confirmation union the orchestrator already accepts.

## 6. Production composition graph

`I4d` composes exactly one production graph:

```text
MDS closed-bar HTTP webhook
→ FilesystemDeploymentCatalog
→ CommittedBarDeploymentSelector
→ CommittedBarOrchestrator
→ StrategyCycleHandoffBoundary
→ StrategyRuntimeOrchestrator
    → shared StrategyInstanceRuntimeStateRepository
    → shared StrategyInstanceKeyedMutexRegistry
    → OpenPositionResolver
        → ABI open-position HTTP adapter (I4c)
    → StrategyUseCaseRouter
        → Engine live-entry HTTP adapter (I4c)
        → Engine open-trade HTTP adapter (I4c)
    → EntryReconciliationOrchestrator
        → entry execution bridge (I4c)
            → ABI entry-package HTTP client
```

`I4d` replaces the current utility-only `build_application` graph with this
complete one; it does not introduce a second composition root or a parallel
bootstrap path.

## 7. Config and client lifecycle

New environment variables, following the existing `RUNTIME_*` convention in
`strategy_runtime.config.loader`:

```text
RUNTIME_STRATEGY_ENGINE_BASE_URL
RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS

RUNTIME_ABI_BASE_URL
RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS
RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS
```

Ownership rules for `I4d`:

- one repository instance and one keyed-mutex registry for one constructed
  Runtime application/service lifetime: exactly one
  `StrategyInstanceRuntimeStateRepository` instance and one
  `StrategyInstanceKeyedMutexRegistry` instance; I5 reuses both rather than
  constructing its own;
- HTTP clients for Engine and ABI are constructed once at startup with bounded
  connect/read timeouts and closed on shutdown;
- test overrides (fakes injected in place of the HTTP adapters) remain
  supported through the same seams `build_application` already uses for
  `strategy_cycle_handoff`, but are never the production default.

## 8. Readiness and failure semantics

- Startup readiness fails closed (`ready=False`, matching the existing
  not-ready path in `build_application`) when required production
  configuration (base URLs, timeouts) is missing or invalid — the same
  pattern already used for invalid `RuntimeConfig`.
- The default handoff wires into the semantic `StrategyRuntimeOrchestrator`;
  an unwired/no-op handoff is a test-only override, not a production
  possibility once `I4d` lands.
- Every outbound call inside the keyed critical section keeps the bounded
  timeout and no-retry rules already fixed by
  `runtime-abi-entry-reconciliation-master-plan.md` §25; `I4d` does not
  relax them for production wiring convenience.

## 9. E2E acceptance boundary

`I4d`'s vertical integration test proves:

```text
POST /v1/webhooks/closed-bar
→ selected deployment
→ ABI position_open=false
→ Engine desired_entry
→ reconciliation APPLY
→ ABI entry-package acknowledgement
→ state save
→ CurrentTradeCycle
```

Required failure-path and no-op coverage:

- `desired_entry=null` on an initially empty aggregate
  (`source_state.current_trade_cycle=null`) → `NO_OP` → zero ABI
  entry-package calls → zero repository saves;
- `desired_entry=null` against an existing acknowledged `CurrentTradeCycle` →
  `CANCEL` → exactly one ABI entry-package call → the cycle is cleared only
  after an `EntryPackageAbsent` confirmation, never optimistically before it;
- Strategy Engine error;
- ABI open-position lookup error;
- ABI entry-package rejection (typed public error);
- failed dispatch journal outcome.

Timeout/no-retry coverage applies individually to each of the three outbound
boundaries in the pipeline — ABI open-position lookup, Strategy Engine
projection, and the ABI entry-package call. For each one, verify:

- a bounded timeout is enforced;
- zero automatic retry follows a timeout or failure;
- no repository save follows that failure;
- any downstream call that would depend on the failed one is not invoked
  (e.g. a Strategy Engine timeout must not still trigger an ABI
  entry-package call).

A real executor bot on the other side of ABI is explicitly out of scope; ABI
may still be a fake HTTP server in this test. What must be real is the
Runtime-side HTTP transport, decoding, and composition.

## 10. OpenSpec split: I4c / I4d

- **`I4c` — `runtime-production-outbound-adapters-v1`**: everything in §2–§5.
  Exit condition — every production outbound dependency can be constructed
  and tested in isolation, but none is yet connected to the application or
  bootstrap.
- **`I4d` — `runtime-live-entry-production-composition-v1`**: everything in
  §6–§9. Exit condition — Runtime is fully wired for the live-entry branch,
  MDS webhook → Engine → ABI client → acknowledged Runtime state, with ABI
  optionally still a fake HTTP server.

`I4c` must land and be verified before `I4d` starts; `I4d` composes adapters
`I4c` already contract-tested rather than building them inline.

## 11. Explicit non-scope

Neither `I4c` nor `I4d` include:

- the ABI fill webhook, `AbiExecutionEventOrchestrator`, or any fill/phase
  state machine (I5);
- open-trade/position-management reconciliation or its application
  component;
- entry/fill cross-flow tests or Live V1 writer guardrails spanning both
  writer paths (I6);
- durable persistence, repository CAS, ABI command idempotency, or restart
  recovery;
- any MDS-side change.

## 12. Handoff to I5

I5 (ABI fill webhook and execution state machine) starts only after `I4d` is
verified and archived. I5 reuses the same production
`StrategyInstanceRuntimeStateRepository` instance and the same
`StrategyInstanceKeyedMutexRegistry` instance `I4d` constructs; it must not
introduce a second repository or a second mutex registry. See
`runtime-abi-entry-delivery-map.md` for the canonical checklist and current
progress against `I4c`/`I4d`/`I5`.
