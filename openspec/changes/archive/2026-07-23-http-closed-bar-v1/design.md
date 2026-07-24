## Context

Market Data Service owns canonical market-data ingestion and emits a notification after a closed bar has been committed. Strategy Runtime consumes that notification as a trigger for internal processing. The HTTP exchange must remain small and stable: Market Data Service reports the committed stream and bar identity, Runtime accepts responsibility for later processing, and all downstream outcomes remain internal to Runtime.

## Goals / Non-Goals

**Goals:**

- Provide one stable closed-bar HTTP endpoint.
- Validate the required request envelope while allowing additive fields.
- Return acknowledgement without waiting for downstream processing.
- Generate an internal correlation identity for each accepted notification.
- Keep pre-acceptance failures distinguishable from post-acceptance processing failures.
- Expose process liveness and startup readiness.

**Non-Goals:**

- No deployment discovery or activation behavior.
- No Strategy Engine or ABI calls.
- No trading commands or exchange actions.
- No validation that the referenced candle exists, is latest, or is continuous.
- No durable inbox, replay, retry, deduplication, stream locking, or ordering guarantee.
- No webhook contract version negotiation.

## Decisions

### Expose one closed-bar notification endpoint

Runtime exposes:

```http
POST /v1/webhooks/closed-bar
```

The request contains:

```json
{
  "instrument": "BTCUSDT.P",
  "timeframe": "5m",
  "open_time_ms": 1784106300000
}
```

The boundary requires:

- `instrument`: non-empty string;
- `timeframe`: non-empty string;
- `open_time_ms`: non-negative integer.

Unknown additional fields are ignored.

**Rationale:** The event is a notification that canonical data is available, not a candle payload. A small additive contract reduces coupling between MDS and Runtime.

### Keep market-data truth in Market Data Service

Runtime does not revalidate whether the referenced candle exists, is closed, is latest, is aligned to the timeframe, or belongs to a ready and continuous stream at the HTTP boundary.

**Rationale:** Those facts are owned by Market Data Service. Later Runtime eligibility or calculation stages may request additional information through their own contracts.

### Acknowledge acceptance independently from downstream outcomes

A valid request received while Runtime is ready returns:

```http
200 OK
```

```json
{"status":"accepted"}
```

The response means that Runtime:

1. validated the request envelope;
2. passed the service readiness check;
3. created an internal trace identifier;
4. registered independent background processing. The generated `trace_id` is immediately discarded by the current implementation.

It does not mean that any strategy was discovered, evaluated, or traded.

**Rationale:** MDS delivery must not wait for or react to Runtime, Strategy Engine, ABI, or exchange outcomes.

### Generate internal trace identity after validation

Runtime creates one `trace_id` only after successful request parsing and readiness checks and before background work is registered. The identifier is not returned to MDS.

**Rationale:** The identifier is generated as a reserved observability hook and is not propagated into background work, journal events, Runtime objects, or external responses.

### Distinguish pre-acceptance and post-acceptance failures

Before acceptance Runtime returns:

- `400 Bad Request` for a request that cannot satisfy the endpoint contract;
- `503 Service Unavailable` when Runtime is live but not ready to accept work;
- `500 Internal Server Error` for an unexpected internal failure before acceptance.

After `200`, all failures are internal Runtime processing failures and cannot change the response already returned to MDS.

### Use independent in-process background work

Each accepted notification is scheduled as independent in-process background work. The endpoint does not wait for its completion.

Accepted limitations:

- no durable queue;
- no replay after restart;
- no recovery of interrupted work;
- no per-stream ordering or lock;
- no deduplication or latest-wins collapse.

**Rationale:** These guarantees belong to later reliability capabilities and are not required for the first HTTP boundary.

### Expose liveness and readiness separately

Runtime exposes:

```http
GET /health/live
GET /health/ready
```

Liveness reports that the process and HTTP service respond. Readiness reports whether startup completed sufficiently for the webhook endpoint to accept work. Readiness is not derived from strategy, MDS stream, Engine, ABI, or exchange state.

## Risks / Trade-offs

- [Accepted work may be lost after process failure] → The capability explicitly provides only in-process handoff; durable delivery is deferred.
- [Concurrent notifications may complete out of order] → Ordering and per-stream serialization are deferred.
- [Unknown fields may hide sender mistakes] → Additive compatibility is preferred; required known fields remain strictly validated.
- [Immediate acknowledgement hides downstream failure from MDS] → This is intentional service decoupling; Runtime owns its own diagnostics and recovery evolution.

## Migration Plan

1. Add the request and response DTOs.
2. Add the closed-bar route and validation behavior.
3. Add internal trace identifier creation and background handoff registration.
4. Add liveness and readiness routes.
5. Add HTTP contract and background-acknowledgement tests.
6. Verify the complete Runtime test suite and OpenSpec change.
