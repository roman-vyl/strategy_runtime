# http-closed-bar Specification

## Purpose
Define the MDS-facing closed-bar webhook, immediate acceptance boundary, pre-acceptance error semantics, internal trace hook, and Runtime liveness and readiness endpoints.
## Requirements
### Requirement: Runtime accepts closed-bar notifications over HTTP
Strategy Runtime SHALL expose one HTTP endpoint for Market Data Service to report a newly committed closed bar.

#### Scenario: Accept a valid closed-bar notification
- **WHEN** MDS sends `POST /v1/webhooks/closed-bar` with non-empty `instrument`, non-empty `timeframe`, and non-negative integer `open_time_ms`
- **AND** Runtime is ready
- **THEN** Runtime returns `200 OK`
- **AND** returns `{"status":"accepted"}`

#### Scenario: Accept additive request fields
- **WHEN** a valid closed-bar request contains additional unknown fields
- **THEN** Runtime ignores those fields
- **AND** accepts the request using the known required fields

#### Scenario: Reject an invalid request
- **WHEN** the request body is malformed, is not an object, omits a required field, uses an invalid field type, contains an empty required string, or contains a negative `open_time_ms`
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status":"rejected","reason":"invalid_webhook"}`
- **AND** does not accept the notification

### Requirement: HTTP acknowledgement is independent from downstream processing
Strategy Runtime SHALL acknowledge an accepted closed-bar notification
without waiting for later application processing. Acceptance means the
event was placed into the bounded committed-bar intake queue, not that it
was processed.

#### Scenario: Return before background work completes
- **WHEN** Runtime accepts a valid closed-bar notification
- **THEN** Runtime enqueues the validated event into the bounded intake
  queue and returns the acknowledgement without waiting for the intake
  worker to dequeue or process it

#### Scenario: Downstream failure does not change acknowledgement
- **WHEN** queued processing fails, or the queued event is never processed
  before the process terminates or restarts
- **THEN** the failure or loss remains internal to Runtime
- **AND** the response already sent to the caller is not changed or
  repeated

#### Scenario: Acceptance does not imply trading success
- **WHEN** Runtime returns `{"status":"accepted"}`
- **THEN** the response does not assert that a strategy was discovered or
  evaluated, or that ABI or an exchange accepted or executed any action

### Requirement: Runtime reserves an internal trace hook for accepted notifications
Strategy Runtime SHALL generate one internal trace identifier for each
accepted closed-bar notification and SHALL currently discard it without
propagating it into queued processing or the HTTP response.

#### Scenario: Create identity before background handoff
- **WHEN** a valid request passes readiness checks and is enqueued
- **THEN** Runtime creates one `trace_id`, enqueues the validated
  `CommittedBarEvent` alone, and does not place `trace_id` in the queued
  item, the orchestration object graph, or the processing journal

#### Scenario: Do not expose flow identity to MDS
- **WHEN** Runtime accepts a closed-bar notification
- **THEN** the HTTP response does not contain `trace_id`

#### Scenario: Rejected requests have no accepted flow
- **WHEN** Runtime rejects a request before acceptance, for any reason
- **THEN** Runtime does not create an accepted flow or enqueue anything
  for that request

### Requirement: Runtime reports pre-acceptance failures
Strategy Runtime SHALL distinguish request validation, readiness,
intake-queue-capacity, intake-stopping, and unexpected internal failures
that happen before acceptance.

#### Scenario: Runtime is not ready
- **WHEN** the process is live but startup readiness is false
- **THEN** the closed-bar endpoint returns `503 {"status":"not_ready"}`
  and does not accept the notification

#### Scenario: Intake queue is at capacity
- **WHEN** Runtime is ready and the bounded intake queue is already at
  its configured capacity
- **THEN** the endpoint returns `503 {"status":"not_ready"}`, does not
  enqueue the event, and does not invoke `CommittedBarOrchestrator
  .process`
- **AND** Runtime emits one server-side log line, reason `queue_full`,
  containing the rejected event's `instrument`, `timeframe`,
  `open_time_ms`, and the configured capacity — the wire response alone
  does not distinguish this from the other `not_ready`-producing cases

#### Scenario: Intake has stopped accepting (shutdown in progress)
- **WHEN** Runtime is ready but shutdown has already called
  `stop_accepting()` on the intake boundary, regardless of remaining
  capacity
- **THEN** the endpoint returns `503 {"status":"not_ready"}`, does not
  enqueue the event, and does not invoke `CommittedBarOrchestrator
  .process`
- **AND** Runtime emits one server-side log line, reason
  `intake_stopping` (distinct from `queue_full`), containing the same
  event fields

#### Scenario: Unexpected failure before acceptance
- **WHEN** an unexpected internal failure occurs before Runtime accepts
  the request
- **THEN** Runtime returns `500 {"status":"error"}` and does not enqueue
  the request's event

### Requirement: Runtime exposes liveness and readiness health endpoints
Strategy Runtime SHALL expose separate process liveness and startup readiness endpoints.

#### Scenario: Report liveness
- **WHEN** a caller requests `GET /health/live`
- **THEN** Runtime returns `200 OK` with `{"status":"live"}`

#### Scenario: Report readiness
- **WHEN** startup readiness succeeded
- **THEN** `GET /health/ready` returns `200 OK` with `{"status":"ready"}`

#### Scenario: Report not ready
- **WHEN** startup readiness did not succeed
- **THEN** `GET /health/ready` returns `503 Service Unavailable` with `{"status":"not_ready"}`

#### Scenario: Keep readiness outside trading state
- **WHEN** Runtime calculates HTTP readiness
- **THEN** it does not depend on deployment activation, MDS stream readiness, Strategy Engine availability, ABI state, position state, or exchange state

### Requirement: Closed-bar HTTP capability does not own market-data or trading semantics
The closed-bar HTTP capability SHALL remain limited to transport validation, acceptance, internal flow creation, and background handoff.

#### Scenario: Do not validate candle truth at ingress
- **WHEN** Runtime receives a structurally valid notification
- **THEN** the HTTP boundary does not verify candle existence, closed status, latest status, timeframe alignment, stream continuity, or stream readiness

#### Scenario: Do not perform downstream work in the HTTP boundary
- **WHEN** Runtime accepts a notification
- **THEN** the HTTP boundary does not scan deployment files
- **AND** does not resolve activation
- **AND** does not call Strategy Engine
- **AND** does not call ABI
- **AND** does not create or modify exchange orders
