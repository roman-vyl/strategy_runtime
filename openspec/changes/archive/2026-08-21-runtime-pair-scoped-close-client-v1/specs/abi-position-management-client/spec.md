## MODIFIED Requirements

### Requirement: Runtime implements the execution port over HTTP against the exact ABI resources
Strategy Runtime SHALL provide an HTTP implementation of
`PositionManagementExecutionPort` that issues `PUT
/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/protection`
for `apply_protection` and `POST
/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/close` for
`close_position`, and no other ABI resource. The retired bodyless `DELETE
.../open-position` close form SHALL NOT be used.

#### Scenario: Apply protection targets the protection resource
- **WHEN** `apply_protection` is called with an `ApplyProtectionCommand`
- **THEN** the adapter issues exactly one `PUT` request to that command's
  strategy-instance/trade-cycle protection resource
- **AND** the request body contains exactly `stop_price` and `take_price`
  taken unchanged from `desired_protection`

#### Scenario: Close position targets the open-position resource without a body
- **WHEN** ABI's close capability moves to `POST .../close` with an
  `exposure_fraction` body
- **THEN** the adapter no longer issues a bodyless `DELETE` request to the
  `open-position` resource for a close
- **AND** this scenario is superseded by "Close position targets the close
  resource with a canonical exposure_fraction body" below

#### Scenario: Close position targets the close resource with a canonical exposure_fraction body
- **WHEN** `close_position` is called with a `ClosePositionCommand`
- **THEN** the adapter issues exactly one `POST` request to that command's
  strategy-instance/trade-cycle `close` resource
- **AND** the request carries a closed JSON body with exactly one field,
  `exposure_fraction`, set to the command's exact-decimal text value
- **AND** the adapter never issues a `DELETE` request to the `open-position`
  resource for a close

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

#### Scenario: Protection response is checked field-by-field before confirming
- **WHEN** ABI returns `200 protection_applied`
- **THEN** `apply_protection` returns `ProtectionAppliedConfirmation` only
  if identifiers, `stop_price`, and `take_price` all equal the sent
  command
- **AND** otherwise raises a protocol failure and returns no confirmation

#### Scenario: Close response is checked field-by-field before confirming
- **WHEN** ABI returns `200 trade_cycle_closed`
- **THEN** `close_position` returns `PositionClosedConfirmation` only if
  both identifiers equal the sent command
- **AND** otherwise raises a protocol failure and returns no confirmation

### Requirement: Every documented public ABI rejection carries one shared typed shape
The adapter SHALL represent every documented `apply_protection` or
`close_position` business rejection — `400 malformed_json`, `415
unsupported_media_type`, `422 validation_failed`, `422
unknown_trade_cycle_binding`, `422 unsupported_exchange_scope`, for
`apply_protection` only `422 position_not_open`, and for `close_position`
only `422 close_execution_incomplete` — as one shared typed public-error
result carrying the response's status code, error code, message, and (only
for `validation_failed`) its `details` array. It SHALL NOT introduce a
separate error type per code. `position_not_open` and
`close_execution_incomplete` SHALL each receive exactly this same shared
treatment, with no external-close, reconciliation, or position-lifecycle
handling derived from either. A status/code combination not documented for
the operation being called — including one valid for the other operation —
is a protocol failure, not a public-error result.

#### Scenario: A documented rejection carries its status, code, and message
- **WHEN** ABI returns a documented status/code pair for the operation
  being called
- **THEN** the adapter raises the shared public-error result carrying that
  exact status code, code, and message
- **AND** carries `details` only when the code is `validation_failed`

#### Scenario: An undocumented status/code combination is a protocol failure
- **WHEN** ABI returns a status or error code not documented for the
  operation being called
- **THEN** the adapter raises a protocol failure, not a public-error result

#### Scenario: close_execution_incomplete is an ordinary close-only public error
- **WHEN** ABI returns `422 close_execution_incomplete` for `close_position`
- **THEN** the adapter raises the shared public-error result carrying that
  code
- **AND** the same code raised for `apply_protection` is a protocol failure

### Requirement: Timeout, network failure, and internal ABI failure share one unavailable classification, with timeout and network distinguished
The adapter SHALL classify a request timeout, any other transport failure
preventing a response, and `500 internal_error` all as ABI being
unavailable — distinct from a public-error result and from a protocol
failure — while still distinguishing a timeout from a non-timeout
transport failure from each other.

#### Scenario: Timeout and non-timeout transport failure are distinguished
- **WHEN** a request to either operation exceeds its configured timeout,
  versus when DNS, connection, TLS, or another non-timeout transport
  failure prevents a response
- **THEN** the adapter raises its respective distinct unavailable outcome
  in each case, and no confirmation is returned in either case

#### Scenario: 500 internal_error is unavailable, not a public error
- **WHEN** ABI returns `500` with error code `internal_error`
- **THEN** the adapter raises the same unavailable classification used for
  a transport failure
- **AND** does not classify it as a public-error result or a protocol
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
