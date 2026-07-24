## Why

Strategy Runtime needs a stable HTTP boundary through which Market Data Service can notify it that a canonical closed bar has been committed. The boundary must acknowledge delivery independently from all later Runtime processing so Market Data Service is not coupled to strategy discovery, Strategy Engine evaluation, ABI interaction, or trading outcomes.

## What Changes

- add `POST /v1/webhooks/closed-bar` as the Runtime closed-bar notification endpoint;
- require `instrument`, `timeframe`, and `open_time_ms` while ignoring additional request fields;
- return immediate `200 {"status":"accepted"}` after validation, readiness checks, trace-hook generation, and background handoff registration;
- return stable validation and readiness errors before acceptance;
- create and currently discard an internal `trace_id` observability hook for each accepted notification without propagating or exposing it;
- process accepted notifications through independent in-process background work;
- provide liveness and readiness endpoints for Runtime service operation;
- keep all downstream strategy, Engine, ABI, order, and exchange behavior outside this capability.

## Capabilities

### New Capabilities

- `http-closed-bar`: Defines the closed-bar HTTP request contract, acknowledgement boundary, pre-acceptance errors, internal trace identity, background handoff semantics, and Runtime health endpoints.

### Modified Capabilities

None.

## Impact

- Runtime FastAPI request and response models.
- HTTP route registration and background task scheduling.
- Runtime startup readiness and health endpoints.
- Internal trace identifier creation.
- HTTP contract and integration tests.
- No changes to deployment discovery, activation, Strategy Engine contracts, ABI contracts, lifecycle state, receipts, or exchange behavior.
