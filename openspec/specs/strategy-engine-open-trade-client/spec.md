# strategy-engine-open-trade-client Specification

## Purpose
TBD - created by archiving change runtime-production-outbound-adapters-v1. Update Purpose after archive.
## Requirements
### Requirement: Runtime exposes one scalar open-trade Engine outbound port implementation
Strategy Runtime SHALL provide a production HTTP adapter that implements the
existing `StrategyEngineOpenTradePort.project_open_trade(...)` contract against
`POST /v1/strategy-evaluations/open-trade` and returns the existing
`OpenTradeProjectionResponse` without coupling application code to HTTP client
types.

#### Scenario: Send one open-trade projection request
- **WHEN** a caller supplies a valid `OpenTradeProjectionRequest`
- **THEN** the adapter issues exactly one `POST` to
  `/v1/strategy-evaluations/open-trade`
- **AND** returns one `OpenTradeProjectionResponse`

#### Scenario: Keep application behavior outside the adapter
- **WHEN** the adapter returns a response
- **THEN** it has not interpreted or persisted the position-management recipe
- **AND** has not issued an exchange action
- **AND** has not mutated or persisted Runtime state
- **AND** has not invoked a Runtime orchestrator or repository

### Requirement: Open-trade wire request regroups existing fields into executed trade receipt
The Runtime HTTP adapter SHALL send a closed JSON body containing exactly
`strategy_id`, `raw_spec`, `ticker`, `base_timeframe`,
`target_bar_open_time_ms`, and `executed_trade_receipt`, where
`executed_trade_receipt` bundles the seven fields the Runtime port model already
carries. The adapter SHALL NOT introduce any new execution fact.

#### Scenario: Serialize the closed request body
- **WHEN** the adapter sends a valid request
- **THEN** the body contains exactly `strategy_id`, `raw_spec`, `ticker`,
  `base_timeframe`, `target_bar_open_time_ms`, and `executed_trade_receipt`
- **AND** `target_bar_open_time_ms` and every timestamp inside
  `executed_trade_receipt` are encoded as JSON integers and not booleans
- **AND** no `strategy_instance_id`, `trade_cycle_id`, `instance_id`, or
  `executed_entry_price` field is present

#### Scenario: Bundle the frozen entry plan and execution bar
- **WHEN** the adapter encodes `executed_trade_receipt`
- **THEN** it contains exactly `side`, `source_plan_bar_open_time_ms`,
  `entry_bar_open_time_ms`, `planned_entry_price`, `initial_stop_price`,
  `initial_take_price`, and `locked_exit_profile`
- **AND** those fields are a pure rename/regroup of the port model's
  `desired_entry` and `entry_bar_open_time_ms`
- **AND** the adapter adds no `executed_entry_price`, exchange identifier, or
  Runtime business identity

### Requirement: Open-trade wire response strictly decodes protection and close signal
The Runtime adapter SHALL treat only HTTP `200` with a UTF-8 JSON body matching
the closed open-trade success shape as successful, and SHALL map the decoded wire
`desired_protection` and `close_signal` into the existing
`runtime.recipes.position_management.DesiredProtection` and `CloseSignal` domain
models without bypassing their invariants.

#### Scenario: Decode a complete projection response
- **WHEN** HTTP `200` contains exactly `desired_protection`, `close_signal`, and
  `diagnostics` with closed `desired_protection` and `close_signal` objects whose
  fields satisfy the Engine wire types and decimal invariants
- **THEN** the adapter returns `OpenTradeProjectionResponse` with
  `DesiredProtection` and `CloseSignal` constructed through the existing domain
  invariants

#### Scenario: Reject an open or malformed success object
- **WHEN** a purported success body has a missing top-level field, unknown
  top-level field, wrong field type, invalid decimal, JSON-numeric price field,
  or an unknown field inside `desired_protection` or `close_signal`
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not return a partial or fallback success

#### Scenario: Reject a non-200 success claim
- **WHEN** an undocumented `2xx` response contains a success-shaped body
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not treat the response as a successful projection

### Requirement: Open-trade diagnostics remain opaque and recursively immutable
The Runtime adapter SHALL decode `diagnostics` as an arbitrary JSON object and
freeze it recursively into the existing `Mapping[str, FrozenJsonValue]` without
validating any fixed internal diagnostics field set.

#### Scenario: Preserve arbitrary diagnostics
- **WHEN** Engine returns any JSON-compatible nested diagnostic object
- **THEN** all keys and values are preserved
- **AND** nested objects and arrays are recursively immutable
- **AND** the adapter requires no fixed diagnostic field list

#### Scenario: Reject a non-object diagnostics value
- **WHEN** Engine returns `diagnostics` as a JSON array, string, number, boolean,
  or null
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not return a success response

#### Scenario: Do not interpret management output
- **WHEN** a projection response is decoded
- **THEN** the adapter does not replace protection, issue a close command, apply
  a phase transition, or mutate state

### Requirement: Decimal fields decode as JSON strings without float conversion; response values are domain-normalized, not byte-preserved
The Runtime adapter SHALL encode outbound decimal request fields and decode
inbound decimal response fields as JSON strings without binary
floating-point conversion. Decoded response decimals (`stop_price`,
`take_price`) map into the existing
`runtime.recipes.position_management.DesiredProtection` domain model and are
therefore domain-normalized by that model's existing invariants; the adapter
does not guarantee byte-for-value / exact-lexeme preservation of the original
Engine response text.

#### Scenario: Encode outbound decimal strings without float conversion
- **WHEN** the adapter sends a request containing decimal values
- **THEN** it encodes them as JSON strings
- **AND** does not convert them through `float`

#### Scenario: Decode inbound decimal strings without float conversion
- **WHEN** Engine returns `stop_price` or `take_price` decimal strings with
  signs, trailing zeros, leading zeros, or exponent notation
- **THEN** the adapter parses them as JSON strings without converting through
  `float`
- **AND** maps the resulting values into the existing `DesiredProtection`
  domain model, which applies its own invariants
- **AND** the adapter does not assert byte-for-value / exact-lexeme
  preservation of the original response text

#### Scenario: Reject JSON numeric decimal fields
- **WHEN** Engine returns `stop_price` or `take_price` as a JSON number
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

#### Scenario: Reject an invalid public error envelope
- **WHEN** a documented non-`2xx` body is not the closed
  `{error, message, details, request_id}` envelope or has a missing, empty, or
  mistyped required field
- **THEN** the adapter raises `StrategyEngineProjectionProtocolError`
- **AND** does not suppress or relabel the response as a valid public error

### Requirement: Transport and protocol failures are distinct for open-trade
The Runtime adapter SHALL expose separate typed failures for a request timeout,
another network transport failure, and an invalid Engine response, sharing the
same failure taxonomy as the live-entry client.

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

### Requirement: Every open-trade failure branch is a StrategyEngineProjectionUnavailable subtype
`StrategyEngineProjectionPublicError` (and its `StrategyEngineMarketStreamNotFound`
subtype), `StrategyEngineProjectionTimeout`, `StrategyEngineProjectionNetworkFailure`,
and `StrategyEngineProjectionProtocolError` SHALL each be a subtype of
`StrategyEngineProjectionUnavailable`, so that every open-trade HTTP failure
branch remains compatible with the canonical `use-case-router` contract, which
treats every Engine HTTP failure as `StrategyEngineProjectionUnavailable`.

#### Scenario: Every failure branch satisfies the router contract
- **WHEN** the open-trade adapter raises `StrategyEngineProjectionPublicError`,
  `StrategyEngineMarketStreamNotFound`, `StrategyEngineProjectionTimeout`,
  `StrategyEngineProjectionNetworkFailure`, or `StrategyEngineProjectionProtocolError`
- **THEN** the raised exception is also an instance of
  `StrategyEngineProjectionUnavailable`
- **AND** the existing `use-case-router` contract observes it as an
  `Unavailable` outcome without modification

### Requirement: The open-trade HTTP attempt is bounded and non-retried
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

### Requirement: Open-trade contract tests verify the implemented Engine contract
The open-trade client layer SHALL include fake-HTTP contract tests covering
request shape, `executed_trade_receipt` regrouping, success decoding, every
typed error branch, timeout, malformed response, redirect rejection, and
single-attempt cardinality.

#### Scenario: Verify the raw outbound request
- **WHEN** fake-HTTP contract tests exercise open-trade requests
- **THEN** they assert the exact method, route, content type, closed JSON body,
  the seven-field `executed_trade_receipt`, absence of `executed_entry_price`
  and Runtime identity fields, and decimal-string preservation

#### Scenario: Verify all response classes
- **WHEN** the fake Engine emits a complete projection, a `market_stream_not_found`,
  another documented public error, mismatched envelopes, malformed payloads,
  non-object diagnostics, timeout, network failure, redirects, and undocumented
  statuses
- **THEN** tests assert the exact typed result or failure
- **AND** assert that no unconfirmed outcome becomes success

