## MODIFIED Requirements

### Requirement: Runtime exposes one scalar ABI open-position lookup port implementation
Strategy Runtime SHALL provide a production HTTP adapter that implements the
existing `AbiOpenPositionLookupPort.lookup(...)` contract against
`GET /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position`
and returns the existing `OpenPositionLookupResponse` without coupling
application code to HTTP client types.

#### Scenario: Send one open-position lookup
- **WHEN** a caller supplies a valid `OpenPositionLookupRequest` containing
  `strategy_instance_id` and `trade_cycle_id`
- **THEN** the adapter issues exactly one `GET` to
  `/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position`
- **AND** returns one `OpenPositionLookupResponse`

#### Scenario: Keep application behavior outside the adapter
- **WHEN** the adapter returns a response
- **THEN** it has not called the use-case router or Strategy Engine
- **AND** has not sent an execution instruction to ABI
- **AND** has not mutated or persisted Runtime state

### Requirement: Open-position lookup encodes two opaque path segments
The Runtime HTTP adapter SHALL percent-encode both `strategy_instance_id` and
`trade_cycle_id` as independent opaque UTF-8 path segments and SHALL NOT
impose Runtime-side regex or format validation on either identifier before
sending it to ABI.

#### Scenario: Encode opaque path identifiers
- **WHEN** `strategy_instance_id` or `trade_cycle_id` contains a slash,
  whitespace, Unicode, a percent character, or another URL-sensitive value
- **THEN** the adapter percent-encodes that segment independently as one
  UTF-8 path segment
- **AND** ABI receives the exact original decoded value for each segment

#### Scenario: Preserve dot-only path identifiers
- **WHEN** `strategy_instance_id` or `trade_cycle_id` is `.` or `..`
- **THEN** the adapter encodes that segment so URL normalization does not
  change the route
- **AND** ABI receives the exact dot-only value for that segment

#### Scenario: Do not invent ABI validation rules
- **WHEN** `strategy_instance_id` or `trade_cycle_id` is any non-empty
  opaque string
- **THEN** the adapter does not reject it for failing a Runtime-imposed regex
  or format
- **AND** a malformed request or path-encoding problem is left for ABI to
  surface as its own public error

### Requirement: Only HTTP 200 with position_open=false means no open position
The Runtime adapter SHALL treat only HTTP `200` with `position_open=false` as
a successful "no open position" outcome and SHALL NEVER coerce any other
status, malformed body, timeout, or transport failure into
`position_open=false`.

#### Scenario: Decode a closed position
- **WHEN** HTTP `200` contains exactly `position_open: false`,
  `first_fill_at_ms: null`, and `average_entry_price: null`
- **THEN** the adapter returns `OpenPositionLookupResponse` with
  `position_open=False` and no fill facts

#### Scenario: Decode an open position
- **WHEN** HTTP `200` contains exactly `position_open: true`, a strictly
  positive integer `first_fill_at_ms`, and a positive exact-decimal
  `average_entry_price` string
- **THEN** the adapter returns `OpenPositionLookupResponse` with
  `position_open=True` and the fill facts preserved
- **AND** `average_entry_price` is normalized without binary-float
  conversion

#### Scenario: Reject a non-positive first_fill_at_ms
- **WHEN** an open response's `first_fill_at_ms` is zero or negative
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not fabricate a position fact

#### Scenario: Never coerce an unexpected 404 into a closed position
- **WHEN** ABI returns an unexpected `404`
- **THEN** the adapter raises a typed failure
- **AND** does not return `position_open=false`

#### Scenario: Reject contradictory facts
- **WHEN** an open response omits either fill fact or a closed response
  includes one
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not fabricate a position fact

#### Scenario: Reject JSON numeric price fields
- **WHEN** ABI returns `average_entry_price` as a JSON number
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not return a success response

#### Scenario: Reject unknown or renamed success fields
- **WHEN** a `200` success body contains `entry_bar_open_time_ms`,
  `executed_entry_price`, or any field other than exactly `position_open`,
  `first_fill_at_ms`, and `average_entry_price`
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not return a success response

### Requirement: Average entry price decodes as a JSON string without float conversion, then domain-normalizes
The Runtime adapter SHALL decode `average_entry_price` as a JSON string
without binary floating-point conversion. The decoded value maps into the
existing `OpenPositionLookupResponse` domain model and is therefore
domain-normalized by that model's existing invariants; the adapter does not
guarantee byte-for-value / exact-lexeme preservation of the original ABI
response text.

#### Scenario: Decode average entry price without float conversion
- **WHEN** ABI returns an accepted positive decimal string with trailing
  zeros, leading zeros, or exponent notation
- **THEN** the adapter parses it as a JSON string without converting it
  through `float`
- **AND** maps the resulting value through the existing
  `OpenPositionLookupResponse` invariants, which domain-normalize it
- **AND** the adapter does not assert byte-for-value / exact-lexeme
  preservation of the original response text

### Requirement: Documented ABI 422 responses become typed public errors with a code-specific envelope
The Runtime adapter SHALL strictly decode a documented ABI `422` response as
one of exactly three closed error shapes, discriminated by `error.code`, and
raise `OpenPositionLookupPublicError` preserving status, code, message, and
details (when the code allows one). The three codes are
`validation_failed`, `unknown_trade_cycle_binding`, and
`unsupported_exchange_scope`; the adapter SHALL NOT accept ABI `400` as a
documented public-error status for this endpoint.

#### Scenario: Decode validation_failed with its required details array
- **WHEN** ABI returns `422` with `error.code = "validation_failed"`
- **THEN** the adapter requires a non-empty `error.details` array of closed
  `{path, message}` objects
- **AND** raises `OpenPositionLookupPublicError` preserving `code`,
  `message`, and `details`
- **AND** rejects the response as `OpenPositionLookupProtocolError` if
  `details` is missing, empty, or contains an item outside the closed
  `{path, message}` shape

#### Scenario: Decode unknown_trade_cycle_binding or unsupported_exchange_scope without a details field
- **WHEN** ABI returns `422` with `error.code` equal to
  `"unknown_trade_cycle_binding"` or `"unsupported_exchange_scope"`
- **THEN** the adapter requires the error object to contain only `code` and
  `message`
- **AND** raises `OpenPositionLookupPublicError` preserving `code` and
  `message`, with `details` absent
- **AND** rejects the response as `OpenPositionLookupProtocolError` if a
  `details` field is present at all

#### Scenario: Reject an invalid public error envelope
- **WHEN** a `422` body is not a closed error envelope, has an unknown
  field for its `code`, or has a missing, empty, or mistyped `code` or
  `message`
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not suppress or relabel the response as a valid public error

#### Scenario: Reject an undocumented error code
- **WHEN** ABI returns `422` with an `error.code` outside the three
  documented values
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not raise `OpenPositionLookupPublicError` for an
  unrecognized code

### Requirement: A documented 500 internal_error response is an availability failure, not a public error
The Runtime adapter SHALL treat a documented `500` status whose body is
exactly the closed `{error: {code: "internal_error", message}}` envelope (no
`details` field) as `OpenPositionLookupUnavailable` (its
availability/`ServiceUnavailable`-style cluster, consistent with the timeout
and network-failure subtypes), not as `OpenPositionLookupPublicError`.

#### Scenario: Classify a documented 500 internal_error as unavailable
- **WHEN** ABI returns `500` with a valid parse of the closed
  `{error: {code: "internal_error", message}}` envelope
- **THEN** the adapter raises `OpenPositionLookupUnavailable`
- **AND** does not raise `OpenPositionLookupPublicError`
- **AND** returns no position fact

#### Scenario: Reject a 500 body outside the documented internal_error shape
- **WHEN** ABI returns `500` with a `details` field present, an `error.code`
  other than `"internal_error"`, or any shape other than the closed
  `{error: {code, message}}` envelope
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not raise `OpenPositionLookupUnavailable`

### Requirement: Open-position contract tests verify the implemented ABI contract
The open-position client layer SHALL include fake-HTTP contract tests
covering both path-segment encodings, both success variants, every typed
error branch and its exact per-code envelope shape, timeout, malformed
response, redirect rejection, and single-attempt cardinality.

#### Scenario: Verify the raw outbound request
- **WHEN** fake-HTTP contract tests exercise open-position lookups
- **THEN** they assert the exact GET method, the two-segment encoded route,
  absence of a request body (and therefore no request `Content-Type`
  header, which does not apply to a bodyless GET), opaque path-segment
  encoding for both `strategy_instance_id` and `trade_cycle_id`, and
  dot-only segment handling for each independently
- **AND** they assert the response `Content-Type: application/json` is
  checked on the response side

#### Scenario: Verify all response classes
- **WHEN** the fake ABI emits a closed position, an open position, an
  unexpected `404`, each of the three documented `422` public errors with
  its exact envelope shape, a documented `500` `internal_error`, mismatched
  envelopes, malformed payloads, timeout, network failure, redirects, and
  undocumented statuses
- **THEN** tests assert the exact typed result or failure
- **AND** assert that no unconfirmed outcome becomes `position_open=false`

#### Scenario: Reject the superseded pre-alignment success shape
- **WHEN** the fake ABI emits the pre-alignment success body
  (`entry_bar_open_time_ms`/`executed_entry_price` field names)
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not return a success response

## ADDED Requirements

### Requirement: An authoritative cross-repository contract test verifies the client against the published ABI OpenAPI document
The open-position client layer SHALL include one contract test that loads the
authoritative ABI OpenAPI document from the sibling repository checkout
(`../abi_executor_bot/docs/openapi/abi-open-position-lookup-api-v1.json`,
relative to the Runtime repository root) and verifies the implemented client
against its exact schema — not merely against local fixtures.

#### Scenario: Verify the exact contract from the authoritative document
- **WHEN** the cross-repository contract test runs
- **THEN** it asserts the exact path template, HTTP method, and both
  required path parameters against the loaded OpenAPI document
- **AND** asserts the success `oneOf`'s two variants, their `position_open`
  `const` values, required/nullable field rules, and `additionalProperties:
  false`
- **AND** asserts every documented error status code and its exact,
  code-specific schema, including which codes require a `details` field and
  which forbid one
- **AND** fails if the client accepts a response shape the document does not
  authorize, or rejects one the document does authorize

#### Scenario: Missing sibling checkout fails with an actionable message
- **WHEN** `../abi_executor_bot` is not present relative to the Runtime
  repository root
- **THEN** the test fails with a message explaining the required canonical
  checkout layout (`BBB_project/{strategy_runtime,abi_executor_bot}`)
- **AND** does not silently skip contract verification
