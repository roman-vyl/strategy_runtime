## 1. HTTP Contract

- [x] 1.1 Add `POST /v1/webhooks/closed-bar`.
- [x] 1.2 Require non-empty `instrument` and `timeframe` strings.
- [x] 1.3 Require non-negative integer `open_time_ms`.
- [x] 1.4 Ignore unknown additional request fields.
- [x] 1.5 Return `200 {"status":"accepted"}` for a valid accepted notification.

## 2. Acceptance Boundary

- [x] 2.1 Check Runtime startup readiness before acceptance.
- [x] 2.2 Create and discard one internal `trace_id` observability hook for each accepted notification.
- [x] 2.3 Keep `trace_id` out of the MDS-facing response and background object graph.
- [x] 2.4 Register independent in-process background work before returning acceptance.
- [x] 2.5 Return without waiting for downstream work to complete.

## 3. Error Semantics

- [x] 3.1 Return `400` for malformed or invalid request payloads.
- [x] 3.2 Return `503` when Runtime is live but not ready.
- [x] 3.3 Return `500` for unexpected failures before acceptance.
- [x] 3.4 Keep failures after `200` internal to Runtime.

## 4. Health Endpoints

- [x] 4.1 Add `GET /health/live`.
- [x] 4.2 Add `GET /health/ready`.
- [x] 4.3 Keep HTTP readiness independent from strategy, MDS stream, Strategy Engine, ABI, and exchange state.

## 5. Verification

- [x] 5.1 Test acceptance with only required fields.
- [x] 5.2 Test acceptance with unknown additional fields.
- [x] 5.3 Test missing, empty, wrong-type, negative, and malformed inputs.
- [x] 5.4 Test not-ready behavior.
- [x] 5.5 Test immediate acknowledgement without waiting for background completion.
- [x] 5.6 Test separate accepted requests receive separate internal trace identifiers.
- [x] 5.7 Test liveness and readiness responses.
- [x] 5.8 Run the complete Runtime test suite.
- [x] 5.9 Validate the OpenSpec change.
