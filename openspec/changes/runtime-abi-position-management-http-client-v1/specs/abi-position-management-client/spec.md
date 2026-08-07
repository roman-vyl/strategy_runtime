## ADDED Requirements

### Requirement: Runtime implements the execution port over HTTP against the exact ABI resources
Strategy Runtime SHALL provide an HTTP implementation of
`PositionManagementExecutionPort` that issues `PUT
/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/protection`
for `apply_protection` and `DELETE
/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position`
for `close_position`, and no other ABI resource.

#### Scenario: Apply protection targets the protection resource
- **WHEN** `apply_protection` is called with an `ApplyProtectionCommand`
- **THEN** the adapter issues exactly one `PUT` request to that command's
  strategy-instance/trade-cycle protection resource
- **AND** the request body contains exactly `stop_price` and `take_price`
  taken unchanged from `desired_protection`

#### Scenario: Close position targets the open-position resource without a body
- **WHEN** `close_position` is called with a `ClosePositionCommand`
- **THEN** the adapter issues exactly one `DELETE` request to that
  command's strategy-instance/trade-cycle open-position resource
- **AND** the request carries no body and no quantity, percentage, or
  close-fraction field

#### Scenario: Opaque identifiers are path-encoded consistently with the existing ABI adapter
- **WHEN** either operation is called with a `strategy_instance_id` or
  `trade_cycle_id` containing a slash, whitespace, Unicode, a percent
  character, or a dot-only value
- **THEN** the adapter percent-encodes that identifier as one UTF-8 path
  segment the same way the existing ABI open-position lookup adapter does
- **AND** ABI receives the exact original decoded value

### Requirement: A confirmation is returned only when the response verifies the sent command
The adapter SHALL return `ProtectionAppliedConfirmation` only when the `200`
protection response's `strategy_instance_id`, `trade_cycle_id`,
`stop_price`, and `take_price` exactly match the sent `ApplyProtectionCommand`.
The adapter SHALL return `PositionClosedConfirmation` only when the `200`
close response's `strategy_instance_id` and `trade_cycle_id` exactly match
the sent `ClosePositionCommand`. Any other `200` body is a protocol failure,
never a confirmation.

#### Scenario: Matching protection response yields a confirmation
- **WHEN** ABI returns `200 protection_applied` with identifiers,
  `stop_price`, and `take_price` equal to the sent command
- **THEN** `apply_protection` returns `ProtectionAppliedConfirmation`
  carrying that same protection

#### Scenario: Mismatched protection response is rejected
- **WHEN** ABI returns `200 protection_applied` but any identifier,
  `stop_price`, or `take_price` differs from the sent command
- **THEN** `apply_protection` raises a protocol failure
- **AND** does not return a confirmation

#### Scenario: Matching close response yields a confirmation
- **WHEN** ABI returns `200 trade_cycle_closed` with identifiers equal to
  the sent command
- **THEN** `close_position` returns `PositionClosedConfirmation`

#### Scenario: Mismatched close response is rejected
- **WHEN** ABI returns `200 trade_cycle_closed` but either identifier
  differs from the sent command
- **THEN** `close_position` raises a protocol failure
- **AND** does not return a confirmation

### Requirement: Documented public ABI errors are surfaced as typed execution errors
The adapter SHALL decode only the documented HTTP status and error-code
combinations for each operation and raise a distinct typed error per code,
preserving the ABI `message` and, for `validation_failed`, the `details`
array. `apply_protection` SHALL recognize `400 malformed_json`, `415
unsupported_media_type`, and `422` with `validation_failed`,
`unknown_trade_cycle_binding`, `unsupported_exchange_scope`, or
`position_not_open`. `close_position` SHALL recognize `422` with
`validation_failed`, `unknown_trade_cycle_binding`, or
`unsupported_exchange_scope`. Any status/code combination not documented
for that operation is a protocol failure, never a typed public error.

#### Scenario: Each documented status/code pair maps to its own typed error
- **WHEN** ABI returns a documented status and error code for the
  operation being called
- **THEN** the adapter raises the typed error corresponding to that exact
  code
- **AND** preserves the response `message`, and `details` when the code is
  `validation_failed`

#### Scenario: position_not_open remains an ordinary execution error
- **WHEN** `apply_protection` receives `422 position_not_open`
- **THEN** the adapter raises the same kind of typed public-error result it
  raises for any other documented `apply_protection` business rejection
- **AND** no external-close, reconciliation, or position-lifecycle handling
  is derived from it

#### Scenario: An undocumented status/code combination is a protocol failure
- **WHEN** ABI returns a status or error code not documented for the
  operation being called — including a status/code pairing valid for the
  other operation but not this one
- **THEN** the adapter raises a protocol failure
- **AND** does not raise a typed public error or return a confirmation

### Requirement: Internal ABI failure is a distinct typed error
The adapter SHALL treat `500 internal_error` as a distinct typed failure
separate from every documented public error and from a protocol failure.

#### Scenario: 500 internal_error is classified distinctly
- **WHEN** ABI returns `500` with error code `internal_error`
- **THEN** the adapter raises the internal-error failure
- **AND** does not classify it as a public business error or a protocol
  failure

### Requirement: Malformed or undocumented responses fail closed as one protocol-failure class
The adapter SHALL treat any response that does not match the exact
documented success or error shape for its status — including invalid JSON,
invalid UTF-8, an unexpected or missing content type, an undocumented HTTP
status, a redirect, a success-shaped body with a missing, extra, or
wrong-typed field, or an error envelope whose code does not match its
status — as one protocol-failure class, without returning a confirmation
or a typed public/internal error.

#### Scenario: Any malformed or undocumented response fails closed
- **WHEN** a response to either operation does not exactly match its
  documented status/body contract, in any of the ways above
- **THEN** the adapter raises a protocol failure
- **AND** returns no confirmation and no other typed error for that
  response

### Requirement: Timeout and non-timeout network failure are distinct
The adapter SHALL raise a distinct typed timeout failure when the request
does not complete within its configured timeout, and a distinct typed
network failure for any other transport failure that prevents a response,
without returning a confirmation in either case.

#### Scenario: Timeout is classified separately from other network failures
- **WHEN** a request to either operation exceeds its configured timeout
- **THEN** the adapter raises the typed timeout failure

#### Scenario: A non-timeout transport failure is classified separately from timeout
- **WHEN** DNS, connection, TLS, or another non-timeout transport failure
  prevents a response
- **THEN** the adapter raises the typed network failure, not the timeout
  failure

### Requirement: Each call is one bounded, non-retried attempt under one shared timeout
The adapter SHALL use one shared, finite, positive timeout for both
operations, issue exactly one HTTP attempt per call with no automatic
retry, and never follow redirects.

#### Scenario: One attempt per call, no retry on failure
- **WHEN** a call to either operation times out, fails at the network
  layer, or receives an invalid response
- **THEN** the adapter has issued exactly one HTTP request for that call
- **AND** issues no automatic retry

#### Scenario: Redirects are never followed
- **WHEN** ABI responds to either operation with a redirect status
- **THEN** the adapter does not issue a request to the redirect target
- **AND** raises a protocol failure

### Requirement: Cross-repository OpenAPI conformance is verified
The implementation SHALL be verified against the authoritative
`abi-position-management-api-v1` OpenAPI document from the sibling
`abi_executor_bot` checkout: both routes, both HTTP methods, the closed
request/response schemas, and every documented status/error-code
combination for each operation.

#### Scenario: Conformance verification confirms the implemented contract
- **WHEN** conformance verification runs against the authoritative
  `abi-position-management-api-v1` document
- **THEN** it confirms the exact methods, routes, closed request/response
  schemas, and status/error-code combinations this capability implements
- **AND** verification fails if the authoritative document is missing or
  incompatible

#### Scenario: Verification is not a production runtime dependency
- **WHEN** the adapter is built or invoked in production
- **THEN** it does not load the sibling repository or its OpenAPI document
  at runtime
