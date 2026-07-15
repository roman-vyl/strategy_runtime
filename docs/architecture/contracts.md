# Agreed Contract Boundaries

This document fixes service-to-service responsibilities. Exact endpoint paths and final field names will be agreed before implementation.

## 1. Market Data Service -> Strategy Runtime

Transport: HTTP webhook.

Trigger: a newly closed canonical bar has been successfully committed for a stream.

Agreed payload:

```json
{
  "instrument": "BTCUSDT.P",
  "timeframe": "1h",
  "open_time_ms": 1784102400000
}
```

Contract meaning:

- the event identifies the newly available closed bar;
- Market Data Service remains authoritative for canonical candles and `ready` state;
- Strategy Runtime does not revalidate continuity;
- the webhook does not contain OHLCV, coverage, stream state, or candle history;
- Strategy Engine reads the canonical candle window it needs directly from Market Data Service.

The webhook means:

> A new canonical closed bar for this stream has been committed and is available for calculation.

## 2. Strategy Runtime -> Strategy Engine

Purpose: request calculation of one active strategy spec against the current state of the market-data streams consumed by that strategy.

Required conceptual input:

```json
{
  "strategy_spec": {},
  "ticker": "BTCUSDT.P",
  "timeframe": "1h"
}
```

Contract meaning:

- no bounded backtest window is supplied;
- no triggering-bar identity or right-edge timestamp is supplied;
- the Market Data Service webhook wakes Strategy Runtime but does not define the calculation point passed to Strategy Engine;
- the supplied `ticker + timeframe` pair is the Runtime-visible base evaluation stream;
- Strategy Runtime binds the active spec to that base stream and does not inspect the spec for additional stream dependencies;
- Strategy Engine independently obtains the market data needed for the current-point calculation;
- Strategy Engine calculates only the current strategy point `0`;
- Strategy Runtime does not select candle ranges, align stream timestamps, or calculate strategy components itself.
- each active runtime strategy has one base evaluation stream;
- only a webhook for that base stream triggers calculation of that strategy;
- webhooks for context or higher-timeframe streams do not independently trigger the same strategy;
- any additional streams used internally by Strategy Engine are outside Runtime's v1 routing and safety index.

The exact request field names and response schema are not fixed yet. Strategy Engine must return a structured current-point result for every successful evaluation. Runtime forwards every such result for a permitted strategy instance to ABI Executor; Runtime does not suppress neutral or unchanged results.


### V1 base-stream-only binding

For v1, Runtime receives `ticker`, `timeframe`, and `strategy_spec`. It treats the supplied `ticker + timeframe` as the one and only base stream visible to Runtime.

Runtime does not compile the spec, request a dependency manifest, or maintain an index of non-base streams. This may be extended in a later architecture revision.

### Known non-base readiness gap

If Strategy Engine internally uses an additional non-base stream and that stream leaves `ready`, Runtime v1 has no dependency knowledge and therefore performs no automatic suspension or ABI cancellation for that strategy.

This is an explicitly accepted v1 limitation, not an implicit guarantee. It must be revisited before Runtime is expected to provide safety reactions for multi-stream strategy dependencies.

### Known cross-stream readiness risk

When base and higher-timeframe candles close on the same wall-clock boundary, asynchronous commit or webhook timing could allow the base-stream-triggered evaluation to observe the new base candle while a required higher-timeframe stream still exposes its previous latest candle.

No mitigation is approved yet. The risk is intentionally recorded for future manual integration testing; no wait barrier, retry, or validation rule is implied.

## 3. Strategy Engine -> Strategy Runtime -> ABI Executor

Strategy Engine returns a neutral strategy decision. It does not return an ABI-native or Bybit-native command.

```text
Strategy Engine neutral decision
        |
        v
Strategy Runtime
        |
        | map to the existing ABI Executor signal contract
        v
ABI Executor POST /signals
```

Agreed ownership:

- Strategy Engine owns strategy semantics and the complete calculated current-point result;
- Strategy Runtime owns permission checks and adaptation from the neutral Engine result to the ABI input contract;
- every successful current-point result for every permitted instance is sent to ABI on every triggering base-stream bar, even when it is neutral or semantically unchanged;
- Runtime does not compare the result with prior bars and does not decide whether an exchange-side change is required;
- ABI Executor owns semantic deduplication and reconciliation against its current pending orders, open positions, and protective orders;
- ABI Executor owns quantity calculation and exchange execution;
- Strategy Runtime does not calculate quantity;
- Strategy Engine does not depend on ABI or Bybit request models.

A future contract extension may carry neutral relative exposure or risk units from Runtime to ABI so ABI can reduce size for riskier or more volatile assets. This is only a recorded future branch; no field or sizing semantics are approved.

The ABI request schema must follow the standalone ABI Executor contract. Strategy Runtime must not invent a competing exchange-order model.

## Not fixed yet

The following are intentionally not part of the current agreed documentation:

- activation and deactivation API;
- runtime instance state model;
- persistence;
- retry policy;
- idempotency strategy;
- ordering and concurrency policy;
- error taxonomy;
- implementation language and framework;
- source-code package structure.

## 4. ABI responsibility handoff

Once ABI Executor confirms that it has accepted the per-bar strategy result, Strategy Runtime considers its responsibility for that handoff complete.

After acceptance, ABI Executor exclusively owns:

- exchange communication;
- order placement attempts;
- retries caused by exchange or network failure;
- confirmation of actual exchange state;
- journaling and reconciliation;
- restart recovery for accepted strategy results and their execution lifecycle.

The exact meaning and response shape of ABI acceptance must be established by the mandatory ABI source audit in `implementation-gates.md`.

## 5. MDS stream-state safety notification

A second MDS-to-Runtime contract is required in addition to the closed-bar webhook.

When a stream transitions from `ready` to any other state, MDS must semantically notify Strategy Runtime and identify the affected stream.

Runtime must then:

1. in v1, suspend only active strategy instances whose configured base stream is the affected stream;
2. stop producing new Engine evaluations and new trading intents for those instances;
3. instruct ABI to cancel pending orders that are not associated with an already open position;
4. preserve open positions and their position-linked protective orders.

The exact MDS endpoint and the exact ABI scoped-cancel contract are blocked by cross-repository gates and are not yet approved. Non-base dependency suspension is outside v1 and remains a documented gap. See `implementation-gates.md`.

## 6. Runtime activation semantics (v1)

An active runtime strategy is eligible for routing from its configured base-stream webhook to Strategy Engine.

When `is_active` changes from `true` to `false`, Strategy Runtime must:

1. remove the strategy from future base-stream routing;
2. stop sending that strategy to Strategy Engine for calculation;
3. instruct ABI Executor to cancel pending entry orders associated with that runtime strategy;
4. preserve already open positions and their stop-loss, take-profit, and other position-linked protective orders.

Deactivation therefore prevents any still-pending entry from opening a new position after the operator has switched the strategy off.

When `is_active` changes from `false` to `true`, v1 does not perform an immediate out-of-band calculation. The strategy becomes eligible for routing again and waits for the next ordinary webhook from its configured base stream.

Immediate calculation at activation time is recorded as a possible future product capability. Supporting it would require a second calculation trigger path independent of the MDS closed-bar webhook, together with explicit semantics for when such a manually triggered current-point decision is allowed to produce a live trading intent. No such path is approved for v1.

## 7. File-backed spec discovery and persisted activation registry (v1)

Runtime v1 uses two separate file-backed stores with different responsibilities.

### Spec directory

A configured directory is the physical registry of available strategy specs.

- the presence of a spec file means that the strategy definition exists;
- placing a new file in the directory does not itself trigger calculation;
- no filesystem watcher or out-of-band evaluation is required in v1;
- discovery happens when an ordinary MDS webhook reaches Runtime.

### Activation registry JSON

A separate JSON file persists the explicit `is_active` override for discovered strategy instances.

On each webhook Runtime reconciles the current spec directory with the activation registry:

1. existing files with existing activation records keep their persisted `is_active` value;
2. a newly discovered strategy with no activation record receives `is_active=true` by default;
3. the new default activation is written to the activation registry before it is treated as an ordinary persisted setting;
4. an API change to `is_active=false` overrides the default and survives restart;
5. a disabled strategy is not sent to Strategy Engine and its pending entry orders are subject to the already agreed deactivation semantics;
6. the activation registry is restored on Runtime restart.

Conceptually:

```text
spec directory
    -> which strategy definitions currently exist

activation registry JSON
    -> whether each discovered strategy is allowed to participate in live routing

HTTPS API
    -> explicit operator override of is_active

MDS webhook
    -> reconciliation point and, when applicable, calculation trigger
```

A newly added spec may participate in the same webhook processing cycle in which it is first discovered, provided its configured `ticker + timeframe` matches that webhook and its default activation record has been created.

### File removal in v1

Manual removal of a spec file from the directory is not observed immediately. Runtime discovers the absence only during the next ordinary MDS webhook reconciliation. Until that reconciliation occurs, the in-memory routing state may still contain the previously discovered strategy.

V1 has no dedicated strategy-delete operation. Before HTTPS activation management exists, there is no supported control-plane mechanism to remove a strategy from calculation other than changing the files and waiting for the next webhook reconciliation.

The intended future lifecycle is explicit and ordered:

1. set `is_active=false` through the Runtime API;
2. Runtime stops future Engine routing and requests cancellation of pending entry orders under the agreed deactivation semantics;
3. only after deactivation, issue a delete operation from the future Runtime frontend/API;
4. the delete operation removes the strategy from the visible registry and deletes its spec file.

Deletion must not be treated as an implicit substitute for deactivation. The exact behaviour of the retained activation record after file deletion remains an implementation detail to design later.

The exact file names, directory layout, strategy identity key, JSON schema, atomic-write procedure, handling of renamed or restored files, and concurrent API update semantics are not yet approved.

## 8. V1 validation limitation

Strategy Runtime v1 does not contain an independent strategy configurator or semantic spec validator.

The initial smoke-test path assumes that strategy files have already been constructed and validated by the existing authoring path, such as Workbench/frontend tooling or the existing CLI validation flow. Correctness of the file placed into the Runtime spec directory is therefore an operator and upstream-tooling responsibility at this stage.

Runtime may still fail to parse a structurally unreadable file or Strategy Engine may reject or fail to evaluate an incompatible spec, but Runtime does not provide an authoritative guarantee that a readable file is semantically valid. A malformed or unsupported spec may therefore fail calculation; the exact Engine failure contract must be established under Gate 01. Runtime must not silently reinterpret or repair strategy semantics.
## 9. Runtime strategy identity (v1)

Runtime v1 separates strategy family, live-instance identity, and configuration identity.

- `strategy_id` identifies the strategy family, for example `ema_pullback`;
- `strategy_version` identifies the family/schema version;
- `instance_id` is the stable operational identity of one concrete runtime strategy instance;
- `config_hash` is a content-derived fingerprint of the current strategy configuration.

For ten EMA Pullback variants with different parameters, all may share the same `strategy_id` while each has a different `instance_id` and normally a different `config_hash`.

The activation registry is indexed by `instance_id`, not by file name and not by `config_hash`. This prevents a disabled strategy from becoming active merely because its file is renamed or its parameters are edited.

Agreed semantics:

1. a previously unseen `instance_id` is a newly discovered runtime strategy and receives the normal default `is_active=true`;
2. a known `instance_id` retains its persisted `is_active` value;
3. if the same `instance_id` is observed with a different `config_hash`, Runtime treats it as an updated configuration of the same live instance and does not reset `is_active`;
4. two simultaneously present files with the same `instance_id` are a conflict and must not be chosen arbitrarily for execution;
5. the same `instance_id` is the natural scope key for Runtime-to-ABI operations such as cancelling pending entry orders;
6. file names remain physical locations only and are not authoritative identity.

Runtime must not independently reimplement Strategy Engine's canonical hashing rules. How Runtime obtains the authoritative `config_hash` is part of the Strategy Engine contract-adaptation gate.

The operator must not edit files in the filesystem area consumed by the Runtime container; a new configuration must be added as a new spec file instead.


## 10. Direct webhook processing and responsibility boundaries (v1)

Runtime v1 processes each webhook directly. It does not introduce an internal job queue, calculation-status model, webhook deduplication, retry workflow, or recovery state unless integration testing demonstrates a real need for them.

For each matching active strategy, Runtime calls Strategy Engine. If the Engine HTTP call fails, times out, returns a non-success status, or returns an unusable response, Runtime records the integration failure and produces no ABI signal for that strategy. Failure of one strategy does not transfer responsibility for strategy semantics or recovery into Runtime.

When Runtime successfully submits a signal to ABI Executor, execution responsibility belongs to ABI. Exchange communication, quantity calculation, exchange rejections, retry policy, final failure handling, execution journaling, reconciliation, and restart recovery remain entirely inside ABI. Runtime must not reproduce or interpret ABI's internal execution lifecycle.

The exact ABI acceptance and failure contract remains subject to the existing ABI integration gate. Queues, deduplication, processing states, and recovery orchestration are future scaling branches to be reconsidered only if observed latency, overlap, duplicate delivery, or restart behaviour makes them necessary.


## 8. Closed-bar webhook acknowledgement semantics

The MDS-to-Runtime business flow is a one-way notification with an HTTP acknowledgement. A Runtime `2xx` response means only that the webhook reached the live Runtime API and was accepted for processing. It does not report whether Strategy Engine calculations succeeded, whether ABI accepted every result, or whether exchange state changed. Per-strategy failures remain encapsulated and journalled inside Runtime and the downstream owning services.

Runtime may process the v1 flow synchronously, but the semantic meaning of the HTTP acknowledgement remains delivery acceptance rather than downstream completion. `4xx` is reserved for an unreadable or structurally invalid Runtime request contract. `5xx` is reserved for a Runtime-level failure that prevented acceptance or initiation of the flow, not for an individual Engine or ABI failure.

## 9. Webhook boundary validation

MDS owns the semantic correctness of the closed-bar event: canonical commit, stream identity, and the truth that the bar is available. Runtime performs only minimal defensive validation of its own HTTP boundary: readable JSON, required fields, supported field types, and supported contract version when versioning is introduced. Runtime does not revalidate candle existence, continuity, canonicality, closure, or stream readiness.

## 10. Cold-start behaviour

At cold start Runtime restores local operational configuration, reads the spec directory and activation registry, opens its journal sink, and exposes its HTTP API. Startup does not trigger Strategy Engine calculation and does not send anything to ABI. Runtime waits for the next MDS webhook because the closed-bar endpoint is the only approved live calculation trigger in v1.
