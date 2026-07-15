# Runtime Journal Model

This document fixes the agreed semantic model for Strategy Runtime journaling. It defines architectural intent only; it does not require a central journal service or a complex persistence subsystem in v1.

## 1. Two-stage journal architecture

### Runtime v1

Strategy Runtime writes a local append-only JSONL journal containing typed, structured event objects.

The local journal is a first implementation of the event model, not a text dump and not a source of runtime state. It exists so Runtime activity can be inspected now and later published into a shared journal without redesigning the meaning of the records.

### Future Central Journal

A future standalone module, referred to as the **Central Journal**, will receive events emitted by all system services within their own responsibility boundaries.

Conceptually:

```text
Market Data Service ----\
Strategy Runtime --------+--> Central Journal
Strategy Engine ---------+
ABI Executor ------------/
```

The shared journal model is mandatory for the financially responsible live path: Market Data Service, Strategy Runtime, Strategy Engine, and ABI Executor. Each of those modules must eventually emit typed, timestamped events within its own responsibility boundary using compatible correlation semantics. Backtest-only modules, including Research Service, are intentionally outside this requirement because they do not own live financial decisions or exchange execution.

The Central Journal is expected to store, order, filter, correlate, and present events from multiple services so cross-service behaviour can be analysed. Examples include distinguishing:

- Runtime received and routed a trigger, but Strategy Engine did not complete;
- Strategy Engine produced a decision, but Runtime did not reach ABI;
- Runtime delivered a signal, but ABI did not accept responsibility;
- ABI accepted the signal, but later exchange execution failed inside ABI.

Each module journals only the events that belong to its own responsibility. Runtime must not duplicate Engine calculation internals or ABI exchange-lifecycle events.

## 2. Unit of journaling

One incoming Runtime invocation creates one semantic flow. For the closed-bar path, one MDS webhook creates one `flow_id`.

The flow is not stored as one mutable JSON document. Instead, it is represented by multiple immutable event objects linked by the same `flow_id`.

```text
one incoming webhook
        -> one flow_id
        -> several append-only semantic events
```

This supports partial visibility after a process failure, filtering by event type, future real-time publication, and correlation with events from neighbouring services.

Every event records one fact that occurred at a Runtime responsibility boundary or one meaningful Runtime decision.

## 3. Common event envelope

Every Runtime journal event uses a versioned object envelope with the following conceptual fields:

```json
{
  "schema_version": 1,
  "event_id": "unique-event-id",
  "event_type": "strategy_selection_completed",
  "occurred_at": "2026-07-15T09:10:00.123Z",
  "source": {
    "service": "strategy_runtime",
    "instance": "runtime-instance-id"
  },
  "journal_class": "trading",
  "severity": "info",
  "correlation": {
    "flow_id": "one-runtime-invocation",
    "causation_event_id": "direct-predecessor-event-id"
  },
  "context": {},
  "outcome": {},
  "payload": {}
}
```

The exact serialization field names remain subject to implementation review, but their semantics are agreed.

### `event_id`

Uniquely identifies one journal event.

### `flow_id`

Links every event produced while processing one incoming Runtime invocation. In the closed-bar path, all strategy-selection, Engine, and ABI-boundary events caused by the same webhook share the same `flow_id`.

### `causation_event_id`

Identifies the event that directly caused the current event. It provides an explicit causal chain rather than relying only on timestamp sorting.

### `occurred_at`

Records the event time with sufficient precision and an explicit timezone.

### `context`

Carries stable identities needed to understand the event, where applicable:

```json
{
  "market": {
    "instrument": "BTCUSDT.P",
    "timeframe": "5m",
    "open_time_ms": 1784106300000
  },
  "strategy": {
    "strategy_id": "ema_pullback",
    "strategy_version": "1",
    "instance_id": "btc_5m_tight_stop",
    "config_hash": "authoritative-config-hash"
  }
}
```

Webhook-level events may contain only market context. Events for one selected strategy contain market and strategy context.

### `outcome`

Describes the semantic result in machine-readable form. It is not limited to a boolean.

Conceptually:

```json
{
  "status": "success",
  "code": "actionable_decision"
}
```

The general statuses are:

- `success`;
- `failure`;
- `skipped`.

The event-specific `code` explains the result, such as `no_action`, `actionable_decision`, `strategy_inactive`, `engine_http_error`, or `abi_not_accepted`.

A failure may contain a compact structured error object and diagnostics. Low-level stack traces remain technical logging data and must not replace the semantic event.

### `payload`

Contains fields specific to the event type. Large source objects are not copied into the journal.

Runtime must not journal complete strategy specs, candle arrays, secrets, or large HTTP request and response bodies. It stores stable identifiers and compact facts needed to reconstruct the orchestration path.

## 4. Journal classes and severity

Every event has a mandatory `journal_class`.

V1 supports:

- `trading`;
- `technical`.

The classification belongs to the semantic event, not permanently to a code method. The same integration path may produce different event types and classes depending on what occurred.

### Trading events

A trading event explains behaviour relevant to a trader or system operator, including whether a strategy participated in the live path and whether its decision progressed across service boundaries.

Examples:

- which active strategy instances were selected for evaluation;
- a strategy evaluation completed and produced a neutral, unchanged, or change-bearing current-point result;
- a strategy failed to be evaluated;
- the per-bar result was sent to ABI;
- ABI accepted or did not accept responsibility for the result;
- an instance was activated, deactivated, or skipped because it was inactive;
- a base-stream safety transition suspended an instance.

### Technical events

A technical event describes Runtime implementation or infrastructure behaviour useful for development and operations.

Examples:

- Runtime process started or stopped;
- registry scanning duration;
- a spec file could not be read;
- a serialization error occurred;
- a low-level HTTP transport failure occurred;
- configuration could not be loaded.

An operational failure may be represented by a trader-facing semantic event with compact diagnostics while lower-level details remain available as technical events or ordinary application logs.

### Severity

Severity is separate from journal class and uses:

- `info`;
- `warning`;
- `error`.

`journal_class` answers which semantic view the event belongs to. `severity` answers how serious the event is.

The future Central Journal can therefore build separate trading and technical views by filtering `journal_class`, while retaining severity and shared correlation fields.

## 5. Closed-bar flow semantics

For one closed-bar webhook, Runtime journals the semantic path rather than one mutable summary object.

Conceptually:

```text
webhook_received
        -> registry_reconciled
        -> strategy_selection_completed
        -> per selected instance:
             Engine boundary result
             result classification for observability
             ABI boundary result for every successful evaluation
        -> flow_completed
```

### Strategy selection

For a webhook such as `BTCUSDT.P / 5m`, Runtime records the decision about which strategy instances participate.

The selection result should include compact useful facts such as:

- registry size;
- number of base-stream matches;
- selected active instances;
- inactive matching instances;
- conflicts or unreadable specs where applicable.

Routine stream mismatches should be aggregated rather than producing excessive per-file noise. Unusual conditions such as duplicate `instance_id`, unreadable files, or activation-registry failures may produce their own events.

### Per-strategy Engine boundary

Runtime records whether a selected strategy was sent to Strategy Engine and the semantic result of that request:

- neutral or unchanged current-point result;
- change-bearing current-point result;
- Engine rejection;
- transport failure;
- invalid response.

Runtime records only the orchestration facts and stable IDs. Calculation evidence and component-level diagnostics belong to Strategy Engine.

### ABI boundary

For every successful current-point evaluation, Runtime records that the per-bar result was sent to ABI and whether ABI accepted responsibility according to the future audited ABI contract. Runtime does not suppress neutral or unchanged results and does not journal an exchange-side no-op as its own decision; that reconciliation belongs to ABI.

Runtime does not journal Bybit order placement, quantity calculation, retries, exchange rejection reasons, position lifecycle, or reconciliation. Those belong to ABI.

### Flow completion

A final compact `flow_completed` event may summarize counts and duration, while detailed facts remain in the preceding immutable events.

## 6. API interaction semantics

The three principal Runtime-facing API seams have different business meanings even though all use request-response HTTP transport.

### MDS -> Runtime

```text
notification + acknowledgement
```

MDS sends a closed-bar notification. Runtime returns an HTTP acknowledgement but does not return a strategy result to MDS. The business flow is one-way.

### Runtime -> Strategy Engine

```text
evaluation request + semantic response
```

Runtime waits for Strategy Engine to return a neutral current-point decision or an error. This is a synchronous semantic request-response boundary.

### Runtime -> ABI

```text
command + acceptance/rejection response
```

Runtime sends the per-bar strategy result and receives an HTTP response indicating whether ABI accepted responsibility. Acceptance does not necessarily mean the exchange order has already succeeded. Exact acceptance semantics remain governed by the mandatory ABI audit gate.

These interaction types must be distinguishable in journal event types and outcomes.

## 7. Responsibility and recovery boundary

The Runtime journal is diagnostic and auditable history. It is not a transaction ledger or a recovery source of truth.

Runtime does not recover from the journal:

- activation state, which belongs to the activation registry JSON;
- market readiness or candle state, which belongs to MDS;
- accepted signal and order lifecycle, which belongs to ABI;
- strategy calculation state, which belongs to Strategy Engine.

V1 does not introduce event sourcing, journal replay, job states, processing queues, or guaranteed central delivery.

## 8. Future Central Journal integration

The local JSONL implementation should expose a typed event-emission boundary so the same semantic event can later be sent to another sink.

Conceptually:

```text
Runtime semantic event
        +--> local JSONL sink in v1
        \--> Central Journal publisher in the future
```

Central delivery guarantees, buffering, retries, retention, filtering APIs, and storage technology belong to the future Central Journal module. This work is not tracked as a current cross-repository OpenSpec gate. It remains an explicit item in the system master plan: create the standalone Overall Central Journal and integrate the financially responsible live modules—MDS, Strategy Runtime, Strategy Engine, and ABI Executor—while leaving backtest-only modules outside that integration scope.
