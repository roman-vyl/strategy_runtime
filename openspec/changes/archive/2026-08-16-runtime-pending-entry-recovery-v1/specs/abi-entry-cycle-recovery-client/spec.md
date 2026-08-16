## ADDED Requirements

### Requirement: Runtime exposes one scalar ABI recovery-state lookup port implementation
Strategy Runtime SHALL provide a production HTTP adapter implementing a
`AbiEntryCycleRecoveryPort.query(...)` contract against
`GET /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/recovery-state`
and returning a typed `RecoveryStateResponse`, without coupling application
code (`uncertain-exchange-state-resolver`) to HTTP client types.

#### Scenario: Send one recovery-state query
- **WHEN** a caller supplies a valid `strategy_instance_id` and
  `trade_cycle_id`
- **THEN** the adapter issues exactly one `GET` to
  `/v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/recovery-state`
- **AND** returns one `RecoveryStateResponse`

#### Scenario: Keep application behavior outside the adapter
- **WHEN** the adapter returns a response
- **THEN** it has not acquired a keyed mutex, called the use-case router or
  Strategy Engine, or mutated or persisted Runtime state

### Requirement: Recovery-state queries use the same opaque path encoding as the open-position lookup client
The adapter SHALL percent-encode `strategy_instance_id` and `trade_cycle_id`
as independent opaque UTF-8 path segments, with no Runtime-side regex or
format validation, consistent with `abi-open-position-lookup-client`.

#### Scenario: Encode opaque path identifiers
- **WHEN** either identifier contains a slash, whitespace, Unicode, a percent
  character, or another URL-sensitive value
- **THEN** the adapter percent-encodes that segment independently as one
  UTF-8 path segment
- **AND** ABI receives the exact original decoded value for each segment

### Requirement: The four recovery_state values decode strictly, with conditional fields enforced
The adapter SHALL decode a `200` response's `recovery_state` as exactly one
of `entry_order_live`, `position_open`, `terminal_without_fill`, or
`terminal_after_fill`, and SHALL enforce the same cross-field invariant
ABI's contract defines: `applied_entry_package` non-null if and only if
`recovery_state` is `entry_order_live` or `position_open`;
`first_fill_at_ms`/`average_entry_price` both non-null if and only if
`recovery_state` is `position_open`. There is no fifth, time-based
`recovery_state` value — ABI reports insufficient positive evidence through
its existing `500 internal_error` availability-failure shape (see "A
documented 500 internal_error response is an availability failure"), not
through a distinct `200` state.

#### Scenario: Decode entry_order_live
- **WHEN** HTTP `200` reports `recovery_state: "entry_order_live"` with a
  non-null `applied_entry_package` and both fill facts `null`
- **THEN** the adapter returns a `RecoveryStateResponse` of kind
  `entry_order_live` carrying the applied entry package

#### Scenario: Decode position_open
- **WHEN** HTTP `200` reports `recovery_state: "position_open"` with a
  non-null `applied_entry_package` and both fill facts non-null
- **THEN** the adapter returns a `RecoveryStateResponse` of kind
  `position_open` carrying the applied entry package and fill facts

#### Scenario: Decode terminal_without_fill or terminal_after_fill
- **WHEN** HTTP `200` reports `terminal_without_fill` or
  `terminal_after_fill`, with `applied_entry_package` null and both fill
  facts null
- **THEN** the adapter returns a `RecoveryStateResponse` of the matching kind
  carrying no applied entry package or fill facts

#### Scenario: Reject a response violating the cross-field invariant
- **WHEN** `applied_entry_package` is non-null for a state other than
  `entry_order_live`/`position_open`, is null for `entry_order_live`/
  `position_open`, or the fill facts are inconsistent with whether
  `recovery_state` is `position_open`
- **THEN** the adapter raises a typed protocol error
- **AND** does not return a `RecoveryStateResponse`

#### Scenario: Reject an unrecognized recovery_state value
- **WHEN** `recovery_state` is present but not one of the four documented
  values
- **THEN** the adapter raises a typed protocol error

### Requirement: A missing trade-cycle binding is a distinct, typed public error, never a fabricated recovery_state
The adapter SHALL decode ABI's `422 unknown_trade_cycle_binding` response as
a distinct typed public error, not as any `recovery_state` value. The adapter
SHALL NOT document, imply, or provide any helper that treats this error as
equivalent to `terminal_without_fill` or any other `recovery_state` — Runtime
draws no inference at all from a missing binding. If ABI can safely prove
absence for a trade cycle it does not recognize, that proof must be surfaced
as one of ABI's own documented `recovery_state` values by the paired ABI
capability (`abi-entry-cycle-recovery-v1`), not derived by Runtime from this
HTTP status.

#### Scenario: Decode unknown_trade_cycle_binding
- **WHEN** ABI returns `422` with `error.code = "unknown_trade_cycle_binding"`
- **THEN** the adapter raises a typed public error carrying that code
- **AND** does not return a `RecoveryStateResponse`
- **AND** the caller (`uncertain-exchange-state-resolver`) treats this raised
  error identically to a transport or availability failure — leaving
  `pending_entry_recovery` untouched — never as evidence of
  `terminal_without_fill`

### Requirement: A documented 500 internal_error response is an availability failure, covering both genuine query failure and insufficient positive evidence
The adapter SHALL treat a documented `500 internal_error` response the same
way `abi-open-position-lookup-client` treats it for the open-position lookup:
as an availability failure, not a public error and not any `recovery_state`.
This single response shape covers two situations ABI's own contract
deliberately does not distinguish for the caller: a genuine query failure,
and a query that completed cleanly but could not positively establish any of
the four `recovery_state` outcomes. The adapter and its caller treat both
identically — there is no way to tell them apart from this response, and no
need to.

#### Scenario: Classify a documented 500 as unavailable
- **WHEN** ABI returns `500` with the documented `internal_error` envelope
- **THEN** the adapter raises a typed availability failure
- **AND** returns no `RecoveryStateResponse`
- **AND** the caller treats this identically whether the underlying cause
  was a query failure or ABI's inability to positively establish an outcome

### Requirement: The adapter exposes one corrective-action call, distinct from the query
The adapter SHALL expose a second operation for the resolver's one corrective
action (resending CANCEL for a trade cycle ABI reports as `entry_order_live`
while removal was intended), reusing the existing entry-package client's
CANCEL request shape rather than defining a second write contract.

#### Scenario: Corrective cancel reuses the existing entry-package client
- **WHEN** the resolver issues its one corrective action
- **THEN** the adapter constructs the same `EntryPackageRequest` shape with
  `desired_entry: null` that the ordinary `Cancel` execution path already
  uses, and sends it through the existing `AbiEntryPackagePort`
- **AND** this capability does not introduce a second HTTP transport for
  entry-package writes

#### Scenario: The corrective call is not part of the read-only query
- **WHEN** the resolver calls `AbiEntryCycleRecoveryPort.query(...)`
- **THEN** that call alone never causes the corrective cancel — the resolver
  decides whether to issue it based on the query's result, as a separate,
  explicit second call
