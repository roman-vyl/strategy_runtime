## ADDED Requirements

### Requirement: Runtime exposes one scalar ABI open-position lookup port implementation
Strategy Runtime SHALL provide a production HTTP adapter that implements the
existing `AbiOpenPositionLookupPort.lookup(...)` contract against
`GET /v1/strategy-instances/{strategy_instance_id}/open-position` and returns
the existing `OpenPositionLookupResponse` without coupling application code to
HTTP client types.

#### Scenario: Send one open-position lookup
- **WHEN** a caller supplies a valid `OpenPositionLookupRequest`
- **THEN** the adapter issues exactly one `GET` to
  `/v1/strategy-instances/{strategy_instance_id}/open-position`
- **AND** returns one `OpenPositionLookupResponse`

#### Scenario: Keep application behavior outside the adapter
- **WHEN** the adapter returns a response
- **THEN** it has not called the use-case router or Strategy Engine
- **AND** has not sent an execution instruction to ABI
- **AND** has not mutated or persisted Runtime state

### Requirement: Open-position lookup encodes one opaque path segment
The Runtime HTTP adapter SHALL percent-encode `strategy_instance_id` as one
UTF-8 path segment and SHALL NOT impose Runtime-side regex or format validation
on it before sending it to ABI.

#### Scenario: Encode opaque path identifiers
- **WHEN** `strategy_instance_id` contains a slash, whitespace, Unicode, a percent
  character, or another URL-sensitive value
- **THEN** the adapter percent-encodes it as one UTF-8 path segment
- **AND** ABI receives the exact original decoded value

#### Scenario: Preserve dot-only path identifiers
- **WHEN** `strategy_instance_id` is `.` or `..`
- **THEN** the adapter encodes it so URL normalization does not change the route
- **AND** ABI receives the exact dot-only value

#### Scenario: Do not invent ABI validation rules
- **WHEN** `strategy_instance_id` is any non-empty opaque string
- **THEN** the adapter does not reject it for failing a Runtime-imposed regex or
  format
- **AND** a malformed request or path-encoding problem is left for ABI to surface
  as its own public error

### Requirement: Only HTTP 200 with position_open=false means no open position
The Runtime adapter SHALL treat only HTTP `200` with `position_open=false` as a
successful "no open position" outcome and SHALL NEVER coerce any other status,
malformed body, timeout, or transport failure into `position_open=false`.

#### Scenario: Decode a closed position
- **WHEN** HTTP `200` contains exactly `position_open: false`,
  `entry_bar_open_time_ms: null`, and `executed_entry_price: null`
- **THEN** the adapter returns `OpenPositionLookupResponse` with
  `position_open=False` and no entry facts

#### Scenario: Decode an open position
- **WHEN** HTTP `200` contains exactly `position_open: true`, a non-negative
  `entry_bar_open_time_ms`, and an exact-decimal `executed_entry_price` string
- **THEN** the adapter returns `OpenPositionLookupResponse` with
  `position_open=True` and the entry facts preserved
- **AND** the executed entry price is normalized without binary-float conversion

#### Scenario: Never coerce an unexpected 404 into a closed position
- **WHEN** ABI returns an unexpected `404`
- **THEN** the adapter raises a typed failure
- **AND** does not return `position_open=false`

#### Scenario: Reject contradictory facts
- **WHEN** an open response omits either entry fact or a closed response includes
  one
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not fabricate a position fact

#### Scenario: Reject JSON numeric price fields
- **WHEN** ABI returns `executed_entry_price` as a JSON number
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not return a success response

### Requirement: Executed entry price decodes as a JSON string without float conversion, then domain-normalizes
The Runtime adapter SHALL decode `executed_entry_price` as a JSON string
without binary floating-point conversion. The decoded value maps into the
existing `OpenPositionLookupResponse` domain model and is therefore
domain-normalized by that model's existing invariants; the adapter does not
guarantee byte-for-value / exact-lexeme preservation of the original ABI
response text.

#### Scenario: Decode executed entry price without float conversion
- **WHEN** ABI returns an accepted decimal string with signs, trailing zeros,
  leading zeros, or exponent notation
- **THEN** the adapter parses it as a JSON string without converting it
  through `float`
- **AND** maps the resulting value through the existing
  `OpenPositionLookupResponse` invariants, which domain-normalize it
- **AND** the adapter does not assert byte-for-value / exact-lexeme
  preservation of the original response text

### Requirement: Documented ABI non-2xx responses become typed public errors
The Runtime adapter SHALL strictly decode a documented ABI `400`/`422` public
error envelope — a closed top-level object containing only an `error` key,
whose value requires a non-empty `code` and a non-empty `message`, with an
optional `details` — and raise `OpenPositionLookupPublicError` preserving
status, code, message, and details (when present).

#### Scenario: Preserve a documented business rejection
- **WHEN** ABI returns a documented `400` or `422` public error with a closed
  envelope
- **THEN** the adapter raises `OpenPositionLookupPublicError`
- **AND** the exception preserves `status_code`, `code`, `message`, and
  `details` when present

#### Scenario: Accept a public error envelope without details
- **WHEN** ABI returns a documented `400` or `422` public error whose `error`
  object contains only `code` and `message`, omitting `details`
- **THEN** the adapter raises `OpenPositionLookupPublicError`
- **AND** the missing `details` is not treated as a protocol error

#### Scenario: Reject an invalid public error envelope
- **WHEN** a documented non-`2xx` body is not a closed error envelope, has an
  unknown field, or has a missing, empty, or mistyped `code` or `message`
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** does not suppress or relabel the response as a valid public error

### Requirement: A documented 5xx response with a valid envelope is an availability failure, not a public error
The Runtime adapter SHALL treat a documented `5xx` status with a valid parse of
the closed ABI error envelope as `OpenPositionLookupUnavailable` (its
availability/`ServiceUnavailable`-style cluster, consistent with the timeout
and network-failure subtypes), not as `OpenPositionLookupPublicError`.

#### Scenario: Classify a documented 5xx as unavailable
- **WHEN** ABI returns a documented `5xx` status with a valid parse of the
  closed `{error: {code, message}}` envelope, with or without `details`
- **THEN** the adapter raises `OpenPositionLookupUnavailable`
- **AND** does not raise `OpenPositionLookupPublicError`
- **AND** returns no position fact

### Requirement: Transport and protocol failures are distinct for open-position lookup
The Runtime adapter SHALL expose separate typed failures for a request timeout,
another network transport failure, and an invalid ABI response, extending the
existing `OpenPositionResolutionError` hierarchy.

#### Scenario: Classify timeout
- **WHEN** the single ABI request exceeds its configured bounded timeout
- **THEN** the adapter raises `OpenPositionLookupTimeout`
- **AND** the exception is an `OpenPositionLookupUnavailable` subtype
- **AND** returns no position fact

#### Scenario: Classify network failure
- **WHEN** DNS, connection, TLS, socket, or another non-timeout network failure
  prevents a valid response
- **THEN** the adapter raises `OpenPositionLookupNetworkFailure`
- **AND** the exception is an `OpenPositionLookupUnavailable` subtype
- **AND** returns no position fact

#### Scenario: Classify invalid ABI response
- **WHEN** ABI returns an undocumented status, unexpected `404`, incompatible
  content type, malformed JSON, invalid UTF-8, or a body outside the exact DTO
  for its status
- **THEN** the adapter raises `OpenPositionLookupProtocolError`
- **AND** returns no public error or success result

#### Scenario: Do not mask programming failures
- **WHEN** code outside the HTTP transport classification raises an unexpected
  programming exception
- **THEN** the adapter does not relabel it as timeout, network failure, public
  error, or protocol error

### Requirement: The open-position HTTP attempt is bounded and non-retried
The Runtime HTTP adapter SHALL perform exactly one HTTP request with a required
finite positive timeout, automatic retries disabled, and redirect following
disabled.

#### Scenario: Complete in one acknowledged call
- **WHEN** ABI returns a valid response to the request
- **THEN** the adapter has issued exactly one HTTP call
- **AND** returns its decoded typed result

#### Scenario: Do not retry an unconfirmed outcome
- **WHEN** the request times out, the network fails, or the response is invalid
- **THEN** the adapter issues no retry
- **AND** fails closed using the corresponding typed failure

#### Scenario: Do not follow redirects
- **WHEN** ABI returns a redirect response
- **THEN** the adapter does not issue a request to the redirect target
- **AND** raises `OpenPositionLookupProtocolError`

### Requirement: Open-position contract tests verify the implemented ABI contract
The open-position client layer SHALL include fake-HTTP contract tests covering
path-segment encoding, both success variants, every typed error branch, timeout,
malformed response, redirect rejection, and single-attempt cardinality.

#### Scenario: Verify the raw outbound request
- **WHEN** fake-HTTP contract tests exercise open-position lookups
- **THEN** they assert the exact GET method, encoded route, absence of a
  request body (and therefore no request `Content-Type` header, which does
  not apply to a bodyless GET), opaque path-segment encoding, and dot-only
  segment handling
- **AND** they assert the response `Content-Type: application/json` is
  checked on the response side

#### Scenario: Verify all response classes
- **WHEN** the fake ABI emits a closed position, an open position, an unexpected
  `404`, a documented public error, mismatched envelopes, malformed payloads,
  timeout, network failure, redirects, and undocumented statuses
- **THEN** tests assert the exact typed result or failure
- **AND** assert that no unconfirmed outcome becomes `position_open=false`
