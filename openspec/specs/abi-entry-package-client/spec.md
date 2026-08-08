# abi-entry-package-client Specification

## Purpose

Define the Runtime-side outbound port, HTTP consumer contract, strict decoding,
error propagation, timeout behavior, and contract verification for the ABI V1
desired-entry-package endpoint.
## Requirements
### Requirement: Runtime exposes one scalar entry-package outbound port
Strategy Runtime SHALL expose a transport-independent scalar port that accepts
one ownership-scoped entry-package request and returns exactly one typed ABI
success or public-error result.

#### Scenario: Send one present package
- **WHEN** a caller supplies `strategy_instance_id`, `trade_cycle_id`, ticker, a non-null `DesiredEntry`, and a non-null `risk_multiplier`
- **THEN** the port accepts one entry-package request
- **AND** returns one typed result from the single ABI interaction

#### Scenario: Send desired package absence
- **WHEN** a caller supplies `strategy_instance_id`, `trade_cycle_id`, ticker, `desired_entry: null`, and a positive exact-decimal `risk_multiplier`
- **THEN** the port accepts one entry-package absence request
- **AND** returns one typed result from the single ABI interaction

#### Scenario: Reject a missing or null risk multiplier
- **WHEN** `risk_multiplier` is omitted or null regardless of whether `desired_entry` is present
- **THEN** Runtime rejects the request before sending it
- **AND** does not invoke ABI

#### Scenario: Keep application behavior outside the port
- **WHEN** the port returns a result
- **THEN** the client layer has not performed entry reconciliation
- **AND** has not created or modified `CurrentTradeCycle`
- **AND** has not mutated or persisted Runtime state
- **AND** has not invoked a Runtime orchestrator

### Requirement: HTTP adapter calls the exact ABI resource
The Runtime HTTP adapter SHALL issue `PUT` to
`/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/entry-package`
with `Content-Type: application/json` and a closed body containing exactly
`ticker`, `desired_entry`, and `risk_multiplier`.

#### Scenario: Encode opaque path identifiers
- **WHEN** either Runtime-owned identifier contains a slash, whitespace, Unicode, a percent character, or another URL-sensitive value
- **THEN** the adapter percent-encodes that identifier as one UTF-8 path segment
- **AND** ABI receives the exact original decoded value

#### Scenario: Preserve dot-only path identifiers
- **WHEN** an identifier is `.` or `..`
- **THEN** the adapter encodes it so URL normalization does not change the route
- **AND** ABI receives the exact dot-only value

#### Scenario: Preserve ticker without rewriting
- **WHEN** the request ticker is a non-empty Runtime-owned string such as `BTCUSDT.P`
- **THEN** the JSON body contains that exact string
- **AND** the adapter does not trim, canonicalize, change case, or derive it

#### Scenario: Serialize only the three body fields
- **WHEN** the adapter sends a valid request
- **THEN** the request body contains exactly `ticker`, `desired_entry`, and `risk_multiplier`
- **AND** ownership identifiers remain in the path
- **AND** no reconciliation, lifecycle, exchange, or internal Runtime field is added

### Requirement: Request DTO keeps risk multiplier mandatory
The Runtime request DTO SHALL model the body as a closed object with required
`ticker`, nullable `desired_entry`, and a required positive exact-decimal string
`risk_multiplier`. No request variant with a null multiplier SHALL exist.

#### Scenario: Serialize a complete DesiredEntry
- **WHEN** a present-package request is encoded
- **THEN** `desired_entry` contains exactly `side`, `source_plan_bar_open_time_ms`, `planned_entry_price`, `initial_stop_price`, `initial_take_price`, and `locked_exit_profile`
- **AND** `side` is exactly `long` or `short`
- **AND** `source_plan_bar_open_time_ms` is encoded as a JSON integer and not a boolean

#### Scenario: Apply only approved decimal constraints
- **WHEN** a present-package request is constructed
- **THEN** all three price fields and `risk_multiplier` are exact-decimal strings
- **AND** `initial_take_price` and `risk_multiplier` represent values greater than zero
- **AND** Runtime adds no positivity rule for `planned_entry_price` or `initial_stop_price`

#### Scenario: Keep instance risk on package absence
- **WHEN** an absence request is constructed with `desired_entry: null`
- **THEN** `risk_multiplier` remains a required positive exact-decimal string
- **AND** Runtime does not replace it with null or omit it

#### Scenario: Do not add ABI-external DesiredEntry constraints
- **WHEN** a `DesiredEntry` satisfies the approved wire-field types and decimal invariants
- **THEN** the client DTO adds no timestamp range, profile content or length, price-order, decimal regex, or decimal text-length restriction

#### Scenario: Serialize explicit absence
- **WHEN** `desired_entry` is null and `risk_multiplier` is a positive exact-decimal string
- **THEN** the JSON body includes `desired_entry` explicitly as null
- **AND** includes the unchanged non-null `risk_multiplier`
- **AND** neither field is omitted

### Requirement: Exact-decimal text survives the client boundary
The Runtime client SHALL encode and decode exact-decimal values as JSON strings
without binary floating-point conversion and SHALL preserve every accepted
string lexeme unchanged.

#### Scenario: Preserve outbound decimal strings
- **WHEN** a request contains accepted decimal strings with signs, trailing zeros, leading zeros, or exponent notation
- **THEN** the adapter sends the same strings byte-for-value in the decoded JSON body
- **AND** does not convert them through `float`

#### Scenario: Preserve applied decimal strings
- **WHEN** ABI returns an applied acknowledgement with valid decimal strings
- **THEN** Runtime preserves the exact strings in `applied_desired_entry` and `calculated_quantity`
- **AND** does not normalize them through a binary floating-point representation
- **AND** no `accepted_risk_multiplier` field is present or decoded

#### Scenario: Reject JSON numeric decimal fields
- **WHEN** ABI returns any price or calculated quantity as a JSON number
- **THEN** Runtime reports an invalid ABI response
- **AND** does not return a success acknowledgement

### Requirement: Runtime strictly decodes both success DTOs
The Runtime client SHALL treat only HTTP `200` with a UTF-8 JSON body matching
exactly one closed ABI success DTO as successful.

#### Scenario: Decode applied acknowledgement
- **WHEN** HTTP `200` contains exactly `strategy_instance_id`, `trade_cycle_id`, status `entry_package_applied`, `applied_desired_entry`, and `calculated_quantity`
- **AND** all fields satisfy their ABI wire types and decimal invariants
- **THEN** Runtime returns the typed `EntryPackageApplied` result

#### Scenario: Decode absent acknowledgement
- **WHEN** HTTP `200` contains exactly `strategy_instance_id`, `trade_cycle_id`, and status `entry_package_absent`
- **THEN** Runtime returns the typed `EntryPackageAbsent` result

#### Scenario: Reject an open or malformed success object
- **WHEN** a purported success body has a missing field, unknown field (including an obsolete `accepted_risk_multiplier` echo), wrong field type, invalid decimal, invalid `DesiredEntry`, or unknown status
- **THEN** Runtime reports `AbiEntryPackageProtocolError`
- **AND** does not return a partial or fallback success

#### Scenario: Reject a non-200 success claim
- **WHEN** an undocumented `2xx` response contains a success-shaped body
- **THEN** Runtime reports `AbiEntryPackageProtocolError`
- **AND** does not treat the response as acknowledged

### Requirement: Success acknowledgement binds to the originating ownership pair
The Runtime client SHALL compare both identifiers in every decoded success DTO
with the unencoded identifiers from the originating request.

#### Scenario: Accept matching ownership identifiers
- **WHEN** both returned identifiers exactly equal the request
  `strategy_instance_id` and `trade_cycle_id`
- **THEN** the bound success result may be returned

#### Scenario: Reject mismatched strategy instance
- **WHEN** a success response has a different `strategy_instance_id`
- **THEN** Runtime reports `AbiEntryPackageProtocolError`
- **AND** does not return a success result

#### Scenario: Reject mismatched trade cycle
- **WHEN** a success response has a different `trade_cycle_id`
- **THEN** Runtime reports `AbiEntryPackageProtocolError`
- **AND** does not return a success result

### Requirement: Public ABI errors remain typed and exact
The Runtime client SHALL strictly decode the closed public ABI error envelope
and map only the approved HTTP status and code pairs:

| HTTP | Public error code |
|---:|---|
| `400` | `malformed_json` |
| `415` | `unsupported_media_type` |
| `422` | `validation_failed` |
| `500` | `internal_error` |

#### Scenario: Map malformed JSON
- **WHEN** ABI returns HTTP `400` with code `malformed_json` and a non-empty message
- **THEN** Runtime returns the typed malformed-JSON public error
- **AND** preserves `code` and `message`

#### Scenario: Map unsupported media type
- **WHEN** ABI returns HTTP `415` with code `unsupported_media_type` and a non-empty message
- **THEN** Runtime returns the typed unsupported-media-type public error
- **AND** preserves `code` and `message`

#### Scenario: Preserve validation details
- **WHEN** ABI returns HTTP `422` with code `validation_failed`, a non-empty message, and a non-empty `details` array
- **THEN** Runtime returns the typed validation-failed public error
- **AND** preserves every closed detail object's `path` and `message`

#### Scenario: Map internal error safely
- **WHEN** ABI returns HTTP `500` with code `internal_error` and a non-empty message
- **THEN** Runtime returns the typed internal-error public result
- **AND** preserves `code` and `message`

#### Scenario: Reject an invalid public error envelope
- **WHEN** status and code do not match, `details` is missing or empty for `validation_failed`, `details` is present for another code, or either error object contains an unknown field
- **THEN** Runtime reports `AbiEntryPackageProtocolError`
- **AND** does not suppress or relabel the response as a valid public error

### Requirement: Transport and protocol failures are distinct
The Runtime client SHALL expose separate typed failures for a request timeout,
another network transport failure, and an invalid ABI response.

#### Scenario: Classify timeout
- **WHEN** the single ABI request exceeds its configured bounded timeout
- **THEN** Runtime raises `AbiEntryPackageTimeout`
- **AND** returns no applied or absent acknowledgement

#### Scenario: Classify network failure
- **WHEN** DNS, connection, TLS, socket, or another non-timeout network failure prevents a valid response
- **THEN** Runtime raises `AbiEntryPackageNetworkFailure`
- **AND** returns no applied or absent acknowledgement

#### Scenario: Classify invalid ABI response
- **WHEN** ABI returns an undocumented status, incompatible content type, malformed JSON, invalid UTF-8, or a body outside the exact DTO for its status
- **THEN** Runtime raises `AbiEntryPackageProtocolError`
- **AND** returns no public error or success result

#### Scenario: Do not mask programming failures
- **WHEN** code outside the HTTP transport classification raises an unexpected programming exception
- **THEN** the client does not relabel it as timeout, network failure, or invalid ABI response

### Requirement: The HTTP attempt is bounded and non-retried
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
- **AND** reports `AbiEntryPackageProtocolError`

### Requirement: ABI does not return or reconfirm risk multiplier
The Runtime entry-package client SHALL treat `risk_multiplier` as a one-way
operational value Runtime sends to ABI. The ABI applied acknowledgement SHALL NOT
contain `accepted_risk_multiplier` or any other risk-multiplier echo, and the
Runtime decoder SHALL reject an ABI response that still carries such a field.

#### Scenario: Send risk multiplier one-way
- **WHEN** the Runtime client sends an `EntryPackageRequest`
- **THEN** `risk_multiplier` is a required positive exact-decimal string
- **AND** no ABI success response is expected to echo or reconfirm it

#### Scenario: Reject an obsolete risk-multiplier echo
- **WHEN** an ABI applied acknowledgement contains `accepted_risk_multiplier`
- **THEN** the strict decoder reports an unknown field
- **AND** does not return a success acknowledgement
