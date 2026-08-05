## MODIFIED Requirements

### Requirement: HTTP acknowledgement is independent from downstream processing
Strategy Runtime SHALL acknowledge an accepted closed-bar notification
without waiting for later application processing. Acceptance means the
event was placed into the bounded committed-bar intake queue, not that it
was processed.

#### Scenario: Return before queued processing completes
- **WHEN** Runtime accepts a valid closed-bar notification
- **THEN** Runtime enqueues the validated event into the bounded
  committed-bar intake queue
- **AND** returns the HTTP acknowledgement without waiting for the intake
  worker to dequeue or process that event

#### Scenario: Downstream failure does not change acknowledgement
- **WHEN** queued processing fails after Runtime returned `200`
- **THEN** the failure remains internal to Runtime
- **AND** Runtime does not change or repeat the response to MDS

#### Scenario: Acceptance does not imply trading success
- **WHEN** Runtime returns `{"status":"accepted"}`
- **THEN** the response does not assert that a strategy was discovered or
  evaluated
- **AND** does not assert that ABI or an exchange accepted or executed any
  action
- **AND** does not assert that the queued event will be processed before
  the process next terminates or restarts

### Requirement: Runtime reserves an internal trace hook for accepted notifications
Strategy Runtime SHALL generate one internal trace identifier for each
accepted closed-bar notification and SHALL currently discard it without
propagating it into queued processing.

#### Scenario: Create identity before queue handoff
- **WHEN** a valid request passes readiness checks and the intake queue has
  capacity
- **THEN** Runtime creates one `trace_id`
- **AND** enqueues the validated `CommittedBarEvent` alone into the intake
  queue
- **AND** does not place `trace_id` in the queued item, the orchestration
  object graph, or the processing journal

#### Scenario: Do not expose flow identity to MDS
- **WHEN** Runtime accepts a closed-bar notification
- **THEN** the HTTP response does not contain `trace_id`

#### Scenario: Rejected requests have no accepted flow
- **WHEN** Runtime rejects a request before acceptance, whether for
  validation, readiness, or intake-queue-capacity reasons
- **THEN** Runtime does not create an accepted flow for that request
- **AND** does not enqueue anything for that request

### Requirement: Runtime reports pre-acceptance failures
Strategy Runtime SHALL distinguish request validation, readiness,
intake-queue-capacity, and unexpected internal failures that happen before
acceptance.

#### Scenario: Runtime is not ready
- **WHEN** the process is live but startup readiness is false
- **THEN** the closed-bar endpoint returns `503 Service Unavailable`
- **AND** returns `{"status":"not_ready"}`
- **AND** does not accept the notification

#### Scenario: Intake queue is at capacity
- **WHEN** Runtime is ready and the bounded committed-bar intake queue is
  already at its configured capacity
- **THEN** the closed-bar endpoint returns `503 Service Unavailable`
- **AND** returns `{"status":"not_ready"}`
- **AND** does not enqueue the request's event
- **AND** does not invoke `CommittedBarOrchestrator.process` or create any
  other processing work for the rejected request
- **AND** Runtime emits one server-side log line containing the rejected
  event's `instrument`, `timeframe`, `open_time_ms`, and the configured
  queue capacity — the wire response alone does not distinguish this case
  from "Runtime is not ready," since both reuse the same `not_ready`
  envelope

#### Scenario: Unexpected failure before acceptance
- **WHEN** an unexpected internal failure occurs before Runtime accepts the
  request
- **THEN** Runtime returns `500 Internal Server Error`
- **AND** returns `{"status":"error"}`
- **AND** does not enqueue the request's event
