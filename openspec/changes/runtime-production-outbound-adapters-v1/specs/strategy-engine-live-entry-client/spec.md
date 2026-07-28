## ADDED Requirements

### Requirement: Runtime exposes one scalar live-entry Engine outbound port implementation
Strategy Runtime SHALL provide a production HTTP adapter that implements the
existing `StrategyEngineLiveEntryPort.project_live_entry(...)` contract against
`POST /v1/strategy-evaluations/live-entry` and returns the existing
`LiveEntryProjectionResponse` without coupling application code to HTTP client
types.

#### Scenario: Send one live-entry projection request
- **WHEN** a caller supplies a valid `LiveEntryProjectionRequest`
- **THEN** the adapter issues exactly one `POST` to
  `/v1/strategy-evaluations/live-entry`
- **AND** returns one `LiveEntryProjectionResponse`

#### Scenario: Keep application behavior outside the adapter
- **WHEN** the adapter returns a response
- **THEN** it has not performed entry reconciliation
- **AND** has not created or modified `CurrentTradeCycle`
- **AND** has not mutated or persisted Runtime state
- **AND** has not invoked a Runtime orchestrator or repository

### Requirement: Live-entry wire request matches the accepted Engine contract
The Runtime HTTP adapter SHALL send a closed JSON body containing exactly
`strategy_id`, `raw_spec`, `ticker`, `base_timeframe`, and
`target_bar_open_time_ms` with `Content-Type: application/json` and no Runtime
business identity field.

#### Scenario: Serialize the closed request body
- **WHEN** the adapter sends a valid request
- **THEN** the body contains exactly `strategy_id`, `raw_spec`, `ticker`,
  `base_timeframe`, and `target_bar_open_time_ms`
- **AND** `target_bar_open_time_ms` is encoded as a JSON integer and not a boolean
- **AND** no `strategy_instance_id`, `trade_cycle_id`, `instance_id`, or
  `executed_entry_price` field is present

#### Scenario: Preserve raw spec without rewriting
- **WHEN** the request `raw_spec` is a JSON object
- **THEN** the adapter sends that object unchanged
- **AND** does not trim, canonicalize, hash, or derive it

### Requirement: Live-entry wire response is strictly decoded into the existing domain model
The Runtime adapter SHALL treat only HTTP `200` with a UTF-8 JSON body matching
the closed live-entry success shape as successful, and SHALL map the decoded wire
`DesiredEntry` into the existing `runtime.recipes.entry.DesiredEntry` domain
model without bypassing its invariants.

#### Scenario: Decode a singular desired entry
- **WHEN** HTTP `200` contains exactly `desired_entry` with a closed six-field
  `DesiredEntry` object whose fields satisfy the Engine wire types and decimal
  invariants
- **THEN** the adapter returns `LiveEntryProjectionResponse` with a `DesiredEntry`
  constructed through the existing domain invariants

#### Scenario: Decode an absent desire
- **WHEN** HTTP `200` contains exactly `desired_entry: null`
- **THEN** the adapter returns `LiveEntryProjectionResponse` with
  `desired_entry = None`
- **AND** Runtime does not fabricate either side

#### Scenario: Reject an open or malformed success object
- **WHEN** a purported success body has a missing field, unknown field, wrong
  field type, invalid decimal, JSON-numeric price field, or unknown top-level
  field
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not return a partial or fallback success

#### Scenario: Reject a non-200 success claim
- **WHEN** an undocumented `2xx` response contains a success-shaped body
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not treat the response as a successful projection

#### Scenario: Do not add Engine-external DesiredEntry constraints
- **WHEN** a wire `DesiredEntry` satisfies the Engine wire-field types and
  decimal invariants
- **THEN** the wire codec adds no timestamp range, profile content or length,
  price-order, decimal regex, or decimal text-length restriction
- **AND** the existing domain model invariants remain the only additional rules

### Requirement: Exact-decimal text survives the live-entry client boundary
The Runtime adapter SHALL encode and decode exact-decimal values as JSON strings
without binary floating-point conversion.

#### Scenario: Preserve outbound decimal strings
- **WHEN** a request or response contains accepted decimal strings with signs,
  trailing zeros, leading zeros, or exponent notation
- **THEN** the adapter preserves the same strings byte-for-value in the decoded
  JSON
- **AND** does not convert them through `float`

#### Scenario: Reject JSON numeric decimal fields
- **WHEN** Engine returns any price as a JSON number
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not return a success response

### Requirement: Documented Engine non-2xx responses become typed public exceptions
The Runtime adapter SHALL strictly decode the closed Engine error envelope
`{error, message, details, request_id}` for every documented non-`2xx` response
and raise `StrategyEngineProjectionPublicError` preserving `status_code`, `code`,
`message`, `details`, and `request_id`.

#### Scenario: Preserve a documented business rejection
- **WHEN** Engine returns a documented non-`2xx` response with the closed error
  envelope
- **THEN** the adapter raises `StrategyEngineProjectionPublicError`
- **AND** the exception preserves `status_code`, `code`, `message`, `details`,
  and `request_id`

#### Scenario: Distinguish market stream not found
- **WHEN** Engine returns HTTP `404` with code `market_stream_not_found`
- **THEN** the adapter raises `StrategyEngineMarketStreamNotFound`
- **AND** the exception is a `StrategyEngineProjectionPublicError` subtype
- **AND** preserves `status_code`, `code`, `message`, `details`, and
  `request_id`

#### Scenario: Reject an invalid public error envelope
- **WHEN** a documented non-`2xx` body is not the closed
  `{error, message, details, request_id}` envelope or has a missing, empty, or
  mistyped required field
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not suppress or relabel the response as a valid public error

### Requirement: Transport and protocol failures are distinct for live-entry
The Runtime adapter SHALL expose separate typed failures for a request timeout,
another network transport failure, and an invalid Engine response.

#### Scenario: Classify timeout
- **WHEN** the single Engine request exceeds its configured bounded timeout
- **THEN** the adapter raises `StrategyEngineProjectionTimeout`
- **AND** returns no projection

#### Scenario: Classify network failure
- **WHEN** DNS, connection, TLS, socket, or another non-timeout network failure
  prevents a valid response
- **THEN** the adapter raises `StrategyEngineProjectionNetworkFailure`
- **AND** returns no projection

#### Scenario: Classify invalid Engine response
- **WHEN** Engine returns an undocumented status, incompatible content type,
  malformed JSON, invalid UTF-8, or a body outside the exact DTO for its status
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** returns no public error or success result

#### Scenario: Do not mask programming failures
- **WHEN** code outside the HTTP transport classification raises an unexpected
  programming exception
- **THEN** the adapter does not relabel it as timeout, network failure, public
  error, or protocol error

### Requirement: The live-entry HTTP attempt is bounded and non-retried
The Runtime HTTP adapter SHALL perform exactly one HTTP request with a required
finite positive timeout, automatic retries disabled, and redirect following
disabled.

#### Scenario: Complete in one acknowledged call
- **WHEN** Engine returns a valid response to the request
- **THEN** the adapter has issued exactly one HTTP call
- **AND** returns its decoded typed result

#### Scenario: Do not retry an unconfirmed outcome
- **WHEN** the request times out, the network fails, or the response is invalid
- **THEN** the adapter issues no retry
- **AND** fails closed using the corresponding typed failure

#### Scenario: Do not follow redirects
- **WHEN** Engine returns a redirect response
- **THEN** the adapter does not issue a request to the redirect target
- **AND** raises `StrategyEngineProjectionProtocolError`

### Requirement: Live-entry contract tests verify the implemented Engine contract
The live-entry client layer SHALL include fake-HTTP contract tests covering
request shape, success decoding, every typed error branch, timeout, malformed
response, redirect rejection, and single-attempt cardinality.

#### Scenario: Verify the raw outbound request
- **WHEN** fake-HTTP contract tests exercise present and absent desired-entry
  responses
- **THEN** they assert the exact method, route, content type, closed JSON body,
  JSON-integer timestamp, absence of Runtime identity fields, and decimal-string
  preservation

#### Scenario: Verify all response classes
- **WHEN** the fake Engine emits a present `DesiredEntry`, an absent desire, a
  `market_stream_not_found`, another documented public error, mismatched
  envelopes, malformed payloads, timeout, network failure, redirects, and
  undocumented statuses
- **THEN** tests assert the exact typed result or failure
- **AND** assert that no unconfirmed outcome becomes success
