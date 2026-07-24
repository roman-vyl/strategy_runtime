# HISTORICAL RECOVERY AUDIT — NOT A NORMATIVE TARGET ARCHITECTURE

> This file records a repository snapshot from 2026-07-20. It is not a current
> implementation or architecture authority. Current Runtime design is indexed by
> [`../system-plans/README.md`](../system-plans/README.md).

---

# Strategy Runtime Current-State Audit — 2026-07-20

## Purpose

This audit establishes the real implementation state of the recovered Strategy Runtime repository before the repository is aligned with the newer ABI-first lifecycle and the completed Strategy Engine `live-entry` / `open-trade` APIs.

The recovered archive was imported unchanged as Git baseline commit `6ad88d6`.

## Verification baseline

The recovered repository is technically healthy in its own historical contract generation:

- Ruff lint: passed;
- Ruff formatting check: passed;
- strict mypy: passed;
- pytest: 67 passed.

This proves internal consistency of the recovered code. It does not prove compatibility with the current cross-service architecture.

## Implemented capabilities

### 1. Runtime service bootstrap

Implemented in:

- `src/strategy_runtime/bootstrap/application.py`;
- `src/strategy_runtime/bootstrap/main.py`;
- `src/strategy_runtime/config/`.

Present behavior:

- immutable environment-backed configuration;
- local startup validation;
- FastAPI application composition;
- Uvicorn entrypoint;
- liveness and readiness endpoints;
- not-ready fallback application when local startup preparation fails.

### 2. MDS closed-bar ingress

Implemented in:

- `src/strategy_runtime/adapters/http/app.py`;
- `src/strategy_runtime/adapters/http/models.py`;
- `src/strategy_runtime/domain/closed_bar.py`.

Present behavior:

- accepts `instrument`, `timeframe`, and `open_time_ms`;
- rejects malformed input before acceptance;
- ignores additional webhook fields;
- returns `200 {"status":"accepted"}`;
- schedules an in-process FastAPI background task;
- does not wait for downstream processing.

This is a basic ingress slice only. It does not implement durable delivery, stream ordering, duplicate suppression, replay, or per-stream locking.

### 3. Filesystem strategy registry

Implemented in:

- `src/strategy_runtime/adapters/strategy_registry/filesystem.py`;
- `src/strategy_runtime/domain/strategy_registry.py`;
- `src/strategy_runtime/ports/strategy_registry.py`.

Present behavior:

- rescans direct-child visible `*.json` files on each accepted webhook flow;
- shallow-validates the live strategy envelope;
- preserves `raw_spec` as Engine-owned opaque data;
- isolates malformed files;
- detects duplicate `instance_id` groups and excludes all conflicting files;
- performs exact `ticker + base_timeframe` routing;
- exposes deterministic immutable snapshots.

This capability remains useful and should be retained. It does not yet provide immutable strategy revision storage or revision pinning for open trades.

### 4. Persisted activation

Implemented in:

- `src/strategy_runtime/adapters/activation/json_file.py`;
- `src/strategy_runtime/domain/activation.py`;
- `src/strategy_runtime/ports/activation.py`.

Present behavior:

- stores activation as `instance_id -> bool` in a flat JSON document;
- defaults newly matched instances to active;
- writes new activation decisions using temporary file plus `os.replace`;
- preserves explicit inactive values and orphaned records;
- fails closed on corrupt or unreadable activation state;
- serializes in-process reconciliation through a thread lock.

This capability remains useful. There is no operator HTTP API for activation and no transaction with lifecycle/pending/receipt state.

### 5. Append-only Runtime journal

Implemented in:

- `src/strategy_runtime/domain/journal_event.py`;
- `src/strategy_runtime/adapters/journal/jsonl.py`;
- `src/strategy_runtime/ports/journal.py`.

Present behavior:

- immutable typed event envelope;
- flow and causation identifiers;
- trading/technical journal classes;
- severity and structured outcomes;
- compact event-specific payloads;
- append-only JSONL sink;
- best-effort journal behavior that does not abort the accepted flow.

The envelope and JSONL adapter are reusable. Current event types are tied to the old `current-point` pipeline and need extension/replacement for ABI state resolution, lifecycle routing, live-entry, open-trade, receipt creation, and ABI reconciliation.

### 6. Historical Strategy Engine current-point integration

Implemented in:

- `src/strategy_runtime/adapters/strategy_engine/http_client.py`;
- `src/strategy_runtime/domain/strategy_current_point.py`;
- `src/strategy_runtime/ports/strategy_engine.py`.

Present behavior:

- calls `POST /v1/strategy-evaluations/current-point`;
- sends market identity and strategy envelope;
- deliberately omits the webhook target bar;
- parses `strategy_current_point.v1` entry/exit/protection ratios;
- validates response identity and neutral not-ready semantics;
- maps transport, timeout, HTTP, JSON, version, contract, and identity failures into typed categories.

The transport/error-isolation pattern is reusable, but the endpoint, request, response, domain model, and port are superseded by the current two-path Engine architecture.

### 7. Historical background orchestration

Implemented in:

- `src/strategy_runtime/application/receive_closed_bar.py`.

Present flow:

```text
accepted webhook
-> journal flow start
-> filesystem registry reconciliation
-> persisted activation reconciliation
-> for each active matched instance:
     call old Engine current-point endpoint
     journal success/failure
```

The flow is deterministic and isolates per-instance Engine failures. It does not query ABI and therefore cannot choose the correct modern Engine use case.

## Critical incompatibilities with the current architecture

### 1. No ABI-first operational-state gate

The current architecture requires:

```text
committed bar
-> query ABI operational state
-> reconcile local lifecycle
-> choose at most one Engine path
```

Recovered code calls Engine directly after activation reconciliation. It has no ABI port, client, operational-state domain model, or lifecycle coordinator.

### 2. Obsolete single Engine endpoint

Recovered code uses `/current-point`. The approved Engine boundary now has two typed projections:

- `live-entry` for flat/armed lifecycle;
- `open-trade` only after ABI confirms a correlated position is open and Runtime has a matching immutable receipt.

The old `StrategyCurrentPointResult` cannot be adapted by renaming fields. Its semantics are different and it should be replaced behind new ports/adapters.

### 3. Webhook target bar is not sent to Engine

The recovered client intentionally omits `open_time_ms` and lets Engine choose a latest-ready point. This can evaluate a different candle than the webhook that triggered the Runtime cycle.

The current contracts require exact `target_bar_open_time_ms` correlation for both live projections.

### 4. No pending-entry lifecycle or immutable receipt

There are no persisted models or stores for:

- pending entry snapshots;
- ABI order correlation;
- entry fill correlation;
- immutable executed-trade receipts;
- open/closing/closed lifecycle;
- pinned strategy revision;
- per-instance processed-bar cursor.

Therefore open-trade invocation cannot be implemented safely on the current state model.

### 5. No ABI reconciliation

There is no support for:

- pending entry create/replace/cancel reconciliation;
- real position state query;
- desired stop/take reconciliation;
- reduce-only close signal delivery;
- closing state;
- fill/partial-fill/retry/idempotency semantics;
- closure confirmation.

### 6. No committed-bar ordering or idempotency

The ingress accepts every valid webhook and schedules independent in-process background work. There is no protection against:

- duplicate webhook delivery;
- out-of-order bars;
- overlapping flows for the same stream/instance;
- process crash after acknowledgement;
- restart replay gaps.

### 7. Strategy files are mutable, not revision-pinned

Each cycle reads the current file contents. This is acceptable for discovering future entry behavior, but an open trade must remain bound to the exact strategy revision/config used for its accepted entry plan and receipt.

The current registry has no immutable revision store or retrieval-by-hash/version contract.

## Capability snapshot recorded by this audit

| Runtime slice | Real state in recovered code |
|---|---|
| Service bootstrap | Complete |
| Deployment discovery | Partial: scanning, routing, shallow validation, and activation exist; immutable revisions and pinned retrieval do not |
| Persistence | Partial: activation and observability journal exist; lifecycle, pending snapshots, receipts, cursors, and atomic state transitions do not |
| MDS ingress | Partial: basic accepted webhook exists; ordering, idempotency, durability, and stream-state handling do not |
| ABI operational-state contract | Not implemented |
| Lifecycle coordination | Not implemented |
| Engine live-entry and ABI pending reconciliation | Not implemented |
| Fill correlation and receipt creation | Not implemented |
| Engine open-trade integration | Not implemented |
| ABI open-position reconciliation | Not implemented |
| Recovery and safety | Not implemented |
| Concurrency and failure closure | Not implemented beyond per-instance Engine failure isolation |

The recovered repository was therefore not an empty skeleton. It contained a
working service bootstrap, useful deployment discovery, basic MDS ingress, and
partial local persistence, while the semantic lifecycle and external
operational-state contracts were absent.

## Strategy Engine dependency status

The recovered Runtime documentation says the real current-point endpoint was deferred. That statement is obsolete.

The Strategy Engine now provides the approved live capabilities through the completed steps 1–6:

- shared live FeatureFrame acquisition;
- live-entry projection and HTTP endpoint;
- immutable receipt validation;
- start-after-entry management replay;
- post-target desired protection and strategic close signal;
- open-trade HTTP endpoint with typed request/response/error schemas.

Runtime documentation must be updated to consume these actual contracts rather than the superseded current-point contract.

## Code disposition

### Preserve with minor alignment

- project/package/bootstrap skeleton;
- configuration loading pattern;
- health endpoints;
- closed-bar HTTP validation and acknowledgement semantics, subject to durability decision;
- filesystem registry adapter and domain snapshot;
- persisted activation adapter and atomic file replacement;
- journal envelope and JSONL sink;
- identifier factories;
- typed HTTP failure mapping patterns;
- deterministic ordering and per-instance failure-isolation test style.

### Refactor

- split `ReceiveClosedBar` into ingress coordination, lifecycle coordination, and per-instance processing;
- extend configuration for ABI endpoints and lifecycle persistence;
- add exact target-bar propagation through the whole cycle;
- update journal event families and flow completion semantics;
- add immutable strategy revision binding around the existing registry;
- decide whether accepted in-process background work is sufficient for v1 or needs a durable inbox before further live execution.

### Supersede/remove from active path

- `StrategyEnginePort.evaluate_current_point`;
- `HttpStrategyEngineClient` current-point endpoint mapping;
- `StrategyCurrentPointResult` and current-point decision models;
- current-point journal event semantics;
- documentation claiming Runtime sends every successful universal current-point result to ABI.

Historical files may be retained in Git/OpenSpec history, but they should not remain normative active architecture.

### Add

- ABI operational-state port, typed client, and failure taxonomy;
- lifecycle state domain and coordinator;
- pending-entry snapshot model/store;
- immutable executed-trade receipt model/store;
- live-entry Engine port/client/domain result;
- open-trade Engine port/client/domain result;
- pending and open-position ABI reconciliation ports;
- strategy revision store or immutable snapshot binding;
- per-instance/stream bar cursor, ordering, idempotency, and locking;
- recovery/suspension paths;
- tests for real temporal collision scenarios resolved through ABI-first routing.

## Documentation authority

The observations above are retained as an audit snapshot only. Current
architecture and contract authority is:

- `docs/system-plans/README.md`;
- `docs/system-plans/runtime-master-plan.md`;
- `docs/system-plans/runtime-state-and-lifecycle-plan.md`;
- `docs/system-plans/runtime-contract-map.md`;
- active OpenSpec changes under `openspec/changes/`.

This audit assigns no authority to removed architecture packages or deleted
documents.

## OpenSpec disposition

### Completed and still useful

- `bootstrap-runtime-webhook-v1`;
- `add-filesystem-strategy-registry-v1`;
- `add-persisted-strategy-activation-v1`.

These changes should remain historical completed slices, with later changes allowed to revise behavior explicitly.

### Completed historically but superseded

- `add-strategy-engine-current-point-client-v1`.

Do not silently rewrite its historical design into the new architecture. Mark/archive it as superseded and create a new OpenSpec change for ABI-gated live projections and lifecycle routing.

## Recommended next sequence

1. Merge the newer architecture package into this full code repository without deleting the recovered implementation history.
2. Rewrite README and document authority/index so old current-point documents are no longer normative.
3. Preserve the three still-valid completed OpenSpecs and mark the current-point change superseded.
4. Create a fresh Runtime OpenSpec for the next implementation boundary, beginning with ABI operational-state resolution and lifecycle routing rather than directly swapping HTTP endpoints.
5. Audit ABI source and contracts before implementing operational-state and lifecycle coordination.
6. Only after the ABI gate, implement live-entry and open-trade Engine clients in Runtime and connect them through lifecycle selection.
7. Add pending/receipt persistence and recovery before enabling open-trade in a financially responsible path.
