# abi-entry-cycle-recovery-client Specification

## Purpose

TBD - Update Purpose after archive: Runtime's outbound HTTP client for ABI's
new recovery-state lookup.
## Requirements
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
The adapter SHALL retain one corrective CANCEL operation backed by the existing
entry-package client. The uncertain-state resolver may call it after
`entry_order_live` for an uncertain removal or after `entry_order_not_found` for an
uncertain APPLY. Both cases SHALL use the same request shape with `desired_entry:null`
and the pending cycle's exact identity; no second write contract is introduced.

#### Scenario: Corrective cancel reuses the existing entry-package client
- **WHEN** the resolver issues a corrective CANCEL for either eligible recovery row
- **THEN** the adapter sends the ordinary existing `EntryPackageRequest` with
  `desired_entry:null` through the existing `AbiEntryPackagePort`
- **AND** preserves the exact strategy instance and pending trade-cycle identity

#### Scenario: The corrective call is not part of the read-only query
- **WHEN** the resolver calls the recovery `query(...)` operation
- **THEN** that call alone never sends CANCEL
- **AND** the resolver decides whether to call the separate corrective operation from the
  returned state and uncertain APPLY/removal context

### Requirement: Recovery-state success bodies identify the proved entry order
The adapter SHALL require exactly six keys in every `200` recovery-state success body: `recovery_state`, `applied_entry_package`, `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id`, `entry_order_id`. For `position_open`, `entry_order_link_id` SHALL be a non-empty string and `entry_order_id` SHALL be a non-empty string or `null`, and `PositionOpenRecoveryState` SHALL carry both. For every other `recovery_state`, both SHALL be `null`. Any other key set or value SHALL raise `AbiEntryCycleRecoveryProtocolError`.

#### Scenario: position_open with both identifiers
- **WHEN** a `position_open` body carries a non-empty `entry_order_link_id` and a non-empty `entry_order_id`
- **THEN** `PositionOpenRecoveryState` carries both values unchanged

#### Scenario: position_open without an exchange order id
- **WHEN** a `position_open` body carries `entry_order_id: null`
- **THEN** `PositionOpenRecoveryState.entry_order_id` is `null`

#### Scenario: Other states
- **WHEN** an `entry_order_live`, `entry_order_not_found`, `terminal_without_fill` or `terminal_after_fill` body carries a non-null identifier, or lacks either key
- **THEN** the adapter raises `AbiEntryCycleRecoveryProtocolError`

### Requirement: The five recovery_state values decode strictly, with conditional fields enforced
The adapter SHALL decode a `200` response's `recovery_state` as exactly one of
`entry_order_live`, `entry_order_not_found`, `position_open`,
`terminal_without_fill`, or `terminal_after_fill`. It SHALL enforce ABI's cross-field
invariant: `applied_entry_package` is non-null if and only if the state is
`entry_order_live` or `position_open`; `first_fill_at_ms` and
`average_entry_price` are both non-null if and only if the state is `position_open`.

`entry_order_not_found` SHALL decode only with `applied_entry_package`,
`first_fill_at_ms`, and `average_entry_price` all null. Runtime SHALL represent it as an
observation distinct from `terminal_without_fill`; the decoder SHALL NOT attach terminal
meaning or synthesize an applied package. Runtime SHALL NOT require or derive a timestamp,
retention age, retry count, or evidence details from this response: the paired ABI
contract is solely responsible for emitting the state only after its structural,
full-budget execution/order, and freshness rules pass.

#### Scenario: Decode entry_order_live
- **WHEN** HTTP `200` reports `entry_order_live` with a non-null applied package and both
  fill facts null
- **THEN** the adapter returns the matching typed response carrying the package

#### Scenario: Decode position_open
- **WHEN** HTTP `200` reports `position_open` with a non-null applied package and both
  fill facts non-null
- **THEN** the adapter returns the matching typed response carrying package and fill facts

#### Scenario: Decode entry_order_not_found
- **WHEN** HTTP `200` reports `entry_order_not_found` with applied package and both fill
  facts null
- **THEN** the adapter returns the distinct `entry_order_not_found` typed response
- **AND** does not classify it as terminal or absent confirmation

#### Scenario: Decoder does not infer fifth state from an ABI error
- **WHEN** ABI returns `internal_error`, `unknown_trade_cycle_binding`, a transport error,
  or any response other than the exact valid fifth-state DTO
- **THEN** the adapter does not return `entry_order_not_found`
- **AND** does not use local time or marker age to reinterpret the response

#### Scenario: Decode terminal_without_fill or terminal_after_fill
- **WHEN** HTTP `200` reports either terminal state with applied package and both fill
  facts null
- **THEN** the adapter returns the matching typed response with no package or fill facts

#### Scenario: Reject a response violating the cross-field invariant
- **WHEN** any state's applied-package or fill fields violate the conditional invariant,
  including any non-null conditional field for `entry_order_not_found`
- **THEN** the adapter raises a typed protocol error
- **AND** returns no recovery response

#### Scenario: Reject an unrecognized recovery_state value
- **WHEN** `recovery_state` is not one of the five documented values
- **THEN** the adapter raises a typed protocol error

