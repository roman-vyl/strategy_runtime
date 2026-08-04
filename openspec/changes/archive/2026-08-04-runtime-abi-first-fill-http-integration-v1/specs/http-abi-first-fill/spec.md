## ADDED Requirements

### Requirement: Runtime accepts an ABI first-fill notification over a synchronous HTTP endpoint
Strategy Runtime SHALL expose `PUT
/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill`
for ABI to report a trade cycle's first fill, with `strategy_instance_id`
and `trade_cycle_id` carried only in the path and never duplicated in the
request body.

#### Scenario: Accept a valid first-fill notification
- **WHEN** ABI sends `PUT
  /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill`
  with `Content-Type: application/json` and a body containing exactly
  `{"first_fill_at_ms": <strictly positive integer>}`
- **AND** Runtime is ready
- **AND** the application-level first-fill use case completes successfully
- **THEN** Runtime returns `200 OK`
- **AND** returns `{"status": "first_fill_recorded"}`

### Requirement: Path identifiers are opaque strings, carried and forwarded exactly as decoded
`strategy_instance_id` and `trade_cycle_id` SHALL each be treated as an
opaque, non-empty string by the HTTP boundary: Runtime SHALL NOT impose a
regex, UUID shape, or any other format policy on either value, and SHALL
NOT trim, case-normalize, or otherwise transform the decoded path-segment
value before passing it into `AbiFirstFillExecutionEvent`. Each identifier
SHALL be addressed by its own distinct URL path segment, and the caller
SHALL percent-encode each segment per standard URL encoding; Runtime SHALL
pass the exact decoded value of each segment into
`AbiFirstFillExecutionEvent` unchanged.

A literal `/` character inside either identifier is categorically
unsupported: the default Starlette path-segment matcher this endpoint uses
cannot carry a literal `/` within a single `{param}` segment, encoded or
not — a percent-encoded `%2F` decodes to `/` before routing and splits the
intended single segment into two, breaking this route's fixed four-segment
pattern. A dot-only segment (`.` or `..`) has no defined contract at this
boundary: standard HTTP client URL-construction behavior (RFC 3986
dot-segment normalization) may collapse such a segment before a request is
ever sent, upstream of anything this adapter controls, so this requirement
makes no promise — support or rejection — for a dot-only segment value.

#### Scenario: A normal identifier round-trips unchanged
- **WHEN** `strategy_instance_id` or `trade_cycle_id` is a typical
  alphanumeric-with-punctuation identifier (e.g. `"strategy-42"`), properly
  percent-encoded by the caller
- **THEN** the value Runtime passes into `AbiFirstFillExecutionEvent` is
  byte-for-byte identical to the caller's original, unencoded value

#### Scenario: A Unicode identifier round-trips unchanged
- **WHEN** `strategy_instance_id` or `trade_cycle_id` contains non-ASCII
  Unicode characters, properly percent-encoded by the caller as UTF-8
- **THEN** the decoded value Runtime passes into
  `AbiFirstFillExecutionEvent` is identical to the caller's original
  Unicode string

#### Scenario: An identifier containing whitespace round-trips unchanged
- **WHEN** `strategy_instance_id` or `trade_cycle_id` contains embedded
  whitespace, properly percent-encoded by the caller (e.g. a space as
  `%20`)
- **THEN** the decoded value Runtime passes into
  `AbiFirstFillExecutionEvent` retains the whitespace exactly, with no
  trimming

#### Scenario: An identifier containing a literal percent character round-trips unchanged
- **WHEN** `strategy_instance_id` or `trade_cycle_id` contains a literal
  `%` character, properly percent-encoded by the caller (`%` encoded as
  `%25`)
- **THEN** the decoded value Runtime passes into
  `AbiFirstFillExecutionEvent` contains the literal `%` character, not a
  partially- or mis-decoded value

#### Scenario: A slash-containing identifier is not addressable by this endpoint
- **WHEN** a caller needs to address a `strategy_instance_id` or
  `trade_cycle_id` value containing a literal `/` character
- **THEN** no percent-encoding of that value produces a request this
  endpoint's routing can match as one identifier
- **AND** this requirement does not commit to a specific error response
  for that case, since the request never reaches this endpoint's own
  validation logic as intended — it is a Live V1 routing boundary, not a
  validated-and-rejected input

#### Scenario: A dot-only segment has no guaranteed contract
- **WHEN** a caller attempts to address a `strategy_instance_id` or
  `trade_cycle_id` value of exactly `.` or `..`
- **THEN** this requirement makes no guarantee that the segment survives
  standard client-side URL normalization to reach Runtime's router intact
- **AND** this change does not implement a custom routing layer to
  guarantee delivery of a dot-only segment

### Requirement: The request body carries exactly one field, validated strictly
Strategy Runtime SHALL accept a first-fill request body containing exactly
one field, `first_fill_at_ms`, requiring a strict positive integer, and
SHALL reject a body containing any other shape.

#### Scenario: Reject a non-integer first_fill_at_ms
- **WHEN** `first_fill_at_ms` is a `bool`, a `float` (including a
  whole-number float such as `1700000000000.0`), or a `string`
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`

#### Scenario: Reject a zero or negative first_fill_at_ms
- **WHEN** `first_fill_at_ms` is zero or negative
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`

#### Scenario: Reject a missing first_fill_at_ms
- **WHEN** the request body omits `first_fill_at_ms`
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`

#### Scenario: Reject extra body fields
- **WHEN** the request body contains any field other than
  `first_fill_at_ms` — including but not limited to
  `entry_bar_open_time_ms`, `ticker`, `timeframe`, `desired_entry`,
  `quantity`, an average price, an order status, or a fill identifier
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`
- **AND** does not silently ignore the extra field, unlike the closed-bar
  webhook's deliberately permissive additive-field contract

#### Scenario: Reject a malformed request body
- **WHEN** the request body is not valid JSON, or is not a JSON object
  (e.g. a JSON array or a bare scalar)
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`

### Requirement: Media-type handling relies on the existing JSON-object body contract — no separate 406 or 415
Strategy Runtime SHALL require the first-fill request body to parse as a
JSON object, using the same body-validation path already registered on
`create_http_app(...)`, and SHALL NOT introduce a distinct HTTP status for
a missing or incorrect `Content-Type` header beyond the existing `400
{"status":"rejected","reason":"invalid_webhook"}` contract. Runtime SHALL
NOT separately validate the `Accept` header for this endpoint.

#### Scenario: A missing Content-Type header is rejected the same as a malformed body
- **WHEN** a first-fill request is sent with no `Content-Type` header, so
  the body is not parsed as JSON
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`
- **AND** Runtime does not return `415 Unsupported Media Type`

#### Scenario: An incorrect Content-Type header is rejected the same as a malformed body
- **WHEN** a first-fill request is sent with `Content-Type: text/plain` (or
  any non-JSON media type) and a body that would otherwise be valid JSON
- **THEN** Runtime returns `400 Bad Request`
- **AND** returns `{"status": "rejected", "reason": "invalid_webhook"}`
- **AND** Runtime does not return `415 Unsupported Media Type`

#### Scenario: The Accept header is not validated
- **WHEN** a first-fill request carries any `Accept` header value,
  including one that does not include `application/json`
- **THEN** Runtime does not return `406 Not Acceptable` on that basis
- **AND** Runtime's response is governed entirely by the request body and
  path validation rules already specified, not by the `Accept` header

### Requirement: The HTTP adapter constructs AbiFirstFillExecutionEvent and delegates to one injected application callable
The first-fill route SHALL construct
`AbiFirstFillExecutionEvent(strategy_instance_id=<path value>,
trade_cycle_id=<path value>, first_fill_at_ms=<validated body value>)` from
validated path and body input, and SHALL call exactly one injected
application-level callable with that event, performing no other
domain-shaped work itself.

#### Scenario: Adapter builds the event from path and body
- **WHEN** a request passes body validation
- **THEN** the adapter constructs `AbiFirstFillExecutionEvent` using the
  path's `strategy_instance_id` and `trade_cycle_id` and the body's
  `first_fill_at_ms`, unmodified
- **AND** a failure to construct `AbiFirstFillExecutionEvent` (an invalid
  path segment reaching construction) is treated as `400 Bad Request` with
  `{"status": "rejected", "reason": "invalid_webhook"}`

#### Scenario: Adapter calls the application callable exactly once
- **WHEN** a valid `AbiFirstFillExecutionEvent` is constructed and Runtime
  is ready
- **THEN** the adapter calls the injected first-fill application callable
  exactly once, passing that event
- **AND** the adapter does not acquire the shared keyed mutex itself
- **AND** the adapter does not call `StrategyInstanceRuntimeStateRepository`
  directly
- **AND** the adapter does not call `apply_first_fill` directly
- **AND** the adapter does not decide whether a save occurs
- **AND** the adapter does not perform timestamp normalization or
  candle-boundary alignment
- **AND** the adapter does not construct any Strategy Engine-facing DTO

### Requirement: The endpoint acknowledges only after the application callable fully completes
The first-fill route SHALL be a synchronous handler — an ordinary blocking
`def` route or an equivalent guaranteed off-event-loop execution — and
SHALL return its HTTP response only after the injected application
callable has returned or raised, never before, and never through a
background task, queue, or fire-and-forget mechanism.

#### Scenario: Response follows completion, not acceptance
- **WHEN** Runtime processes a valid first-fill request
- **THEN** HTTP validation, event construction, the application callable's
  mutex acquisition, its fresh repository load, its `apply_first_fill`
  call, its conditional save, and its mutex release all complete before
  Runtime constructs any HTTP response
- **AND** Runtime does not use `BackgroundTasks`, an async queue, or any
  other deferred-execution mechanism for this endpoint

#### Scenario: The route does not block the event loop
- **WHEN** the first-fill route is defined
- **THEN** it is declared as a synchronous `def` handler that FastAPI runs
  off the event loop, or an equivalent mechanism guaranteeing the
  blocking mutex-and-repository sequence never runs directly inside an
  `async def` coroutine
- **AND** the existing closed-bar webhook's own `async def` handler and its
  `BackgroundTasks` semantics are unchanged by this requirement

### Requirement: First application and identical retry return the identical success response
Strategy Runtime SHALL return the identical `200
{"status": "first_fill_recorded"}` response for the first successful
first-fill call and for a subsequent identical retry, with no field
distinguishing the two.

#### Scenario: Identical retry returns the same response
- **WHEN** the same valid first-fill request is sent twice for the same
  `strategy_instance_id` and `trade_cycle_id`, with the identical
  `first_fill_at_ms`
- **THEN** both calls return `200`
- **AND** both response bodies are exactly `{"status":
  "first_fill_recorded"}`
- **AND** the response contains no field indicating whether this call
  performed a new application or matched an already-frozen no-op

### Requirement: The success response never exposes Runtime state or internal detail
Strategy Runtime SHALL limit the first-fill success response to exactly
`{"status": "first_fill_recorded"}` and SHALL NOT include
`StrategyInstanceRuntimeState`, `FrozenExecutedEntryContext`,
`DesiredEntry`, `first_fill_at_ms`, `entry_bar_open_time_ms`, or any
repository-internal detail.

#### Scenario: Response body contains only the fixed status field
- **WHEN** Runtime returns a `200` first-fill response
- **THEN** the response body's only field is `status`, with value
  `"first_fill_recorded"`

### Requirement: Typed application exceptions map to a fixed HTTP error contract
Strategy Runtime SHALL map exactly the following typed outcomes from the
first-fill application callable to fixed HTTP responses, and SHALL map
every other exception to `500`.

#### Scenario: Missing aggregate maps to 404
- **WHEN** the application callable raises `StrategyInstanceStateNotFound`
- **THEN** Runtime returns `404 Not Found`
- **AND** returns `{"status": "strategy_instance_state_not_found"}`

#### Scenario: Domain invariant violation maps to 409
- **WHEN** the application callable raises `FirstFillInvariantError` —
  including a missing `current_trade_cycle`, a `trade_cycle_id` mismatch,
  a frozen context already carrying a different `first_fill_at_ms`, or a
  normalized entry bar preceding the source plan bar
- **THEN** Runtime returns `409 Conflict`
- **AND** returns `{"status": "first_fill_conflict"}`

#### Scenario: Not-ready application maps to 503
- **WHEN** Runtime is not ready, or the first-fill application callable is
  not connected
- **THEN** Runtime returns `503 Service Unavailable`
- **AND** returns `{"status": "not_ready"}`
- **AND** does not construct `AbiFirstFillExecutionEvent` or call any
  callable

#### Scenario: Unexpected exception maps to 500
- **WHEN** the application callable raises any exception other than
  `StrategyInstanceStateNotFound` or `FirstFillInvariantError` — including
  a repository failure, a programming error, or an unexpected model error
- **THEN** Runtime returns `500 Internal Server Error`
- **AND** returns `{"status": "internal_error"}`

#### Scenario: Internal alignment ValueError maps to 500, not 400
- **WHEN** `apply_first_fill` lets a `ValueError` propagate unwrapped from
  `align_first_fill_to_entry_bar` — for example because
  `registered_spec_snapshot.base_timeframe` is unsupported — after a
  structurally valid `AbiFirstFillExecutionEvent` was already successfully
  constructed from the request
- **THEN** Runtime returns `500 Internal Server Error`
- **AND** returns `{"status": "internal_error"}`
- **AND** does NOT return `400`, because `base_timeframe` is Runtime's own
  registered configuration, not a field the request supplied

#### Scenario: Error responses never leak internal detail
- **WHEN** Runtime returns any `4xx` or `5xx` first-fill response
- **THEN** the response body does not contain an exception message, a
  stack trace, an error-detail array, a retry hint, or any internal
  Runtime state

### Requirement: The first-fill HTTP capability introduces no business logic and does not duplicate http-closed-bar
The first-fill route SHALL contain only transport validation, event
construction, one delegated application call, and typed-exception-to-status
mapping; it SHALL NOT contain candle-boundary alignment, entry-freezing
logic, or any other domain computation, and it SHALL NOT replace, extend,
or duplicate the existing `http-closed-bar` capability's webhook, its
`BackgroundTasks` acknowledgement, or its health endpoints.

#### Scenario: No domain computation in the route
- **WHEN** the first-fill route executes
- **THEN** it performs no timestamp normalization, candle-grid alignment,
  or entry-context construction itself — those remain entirely inside
  `apply_first_fill`, reached only through the injected application
  callable

#### Scenario: The closed-bar endpoint's contract is unaffected
- **WHEN** this capability is added
- **THEN** `POST /v1/webhooks/closed-bar`'s request/response shape,
  `BackgroundTasks` acknowledgement, and error contract remain exactly as
  already specified by `http-closed-bar`
- **AND** `GET /health/live` and `GET /health/ready` remain unchanged
