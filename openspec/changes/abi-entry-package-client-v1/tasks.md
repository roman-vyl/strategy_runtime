## 1. Client DTOs and Typed Outcomes

- [ ] 1.1 Add closed request DTOs for Runtime-owned identifiers, ticker, nullable `DesiredEntry`, and mandatory positive exact-decimal `risk_multiplier`.
- [ ] 1.2 Enforce that `risk_multiplier` is present and non-null for both a present package and `desired_entry: null`.
- [ ] 1.3 Add closed wire DTOs for `entry_package_applied` and `entry_package_absent` without reusing domain models that impose extra ABI constraints.
- [ ] 1.4 Add the four typed public ABI error results, preserving validation `details` only for `validation_failed`.
- [ ] 1.5 Add distinct typed failures for timeout, network transport failure, and invalid ABI response.

## 2. Outbound Port and Serialization

- [ ] 2.1 Add the scalar transport-independent `AbiEntryPackagePort` returning the exact success/public-error result union.
- [ ] 2.2 Map present and absent requests to a closed body containing exactly `ticker`, `desired_entry`, and `risk_multiplier`.
- [ ] 2.3 Preserve identifiers, ticker, all price strings, and `risk_multiplier` without trimming, canonicalization, or binary floating-point conversion.
- [ ] 2.4 Validate exact-decimal text using ABI wire invariants while preserving every accepted string lexeme unchanged.

## 3. HTTP Adapter

- [ ] 3.1 Implement the exact `PUT /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/entry-package` adapter with JSON request and response handling.
- [ ] 3.2 Percent-encode each opaque identifier as one UTF-8 path segment, including slash, percent, Unicode, whitespace, and dot-only values.
- [ ] 3.3 Require a finite positive timeout and perform exactly one request with retries and redirect following disabled.
- [ ] 3.4 Map timeout and non-timeout network failures to their distinct typed failures without masking programming errors.
- [ ] 3.5 Keep the adapter unconnected to reconciliation, `CurrentTradeCycle`, Runtime state repositories, orchestrators, and production composition.

## 4. Strict Response Decoding

- [ ] 4.1 Strictly decode only HTTP `200` closed applied and absent DTOs, rejecting missing fields, unknown fields, wrong types, invalid decimals, and unknown statuses.
- [ ] 4.2 Verify both success identifiers exactly match the originating unencoded `strategy_instance_id` and `trade_cycle_id`.
- [ ] 4.3 Strictly decode the `400 malformed_json`, `415 unsupported_media_type`, `422 validation_failed`, and `500 internal_error` status/code pairs.
- [ ] 4.4 Preserve non-empty validation details exactly and reject missing, empty, misplaced, or structurally invalid `details`.
- [ ] 4.5 Map undocumented statuses, redirects, incompatible content types, invalid UTF-8 or JSON, status/code mismatches, and all other schema violations to `AbiEntryPackageProtocolError`.
- [ ] 4.6 Ensure no timeout, network failure, public ABI error, or invalid response can produce a success acknowledgement.

## 5. Fake ABI Contract Tests

- [ ] 5.1 Add a controllable fake ABI server that records request count, raw encoded path, headers, and decoded JSON and can emit every contract response class.
- [ ] 5.2 Test present and absent requests, including a mandatory non-null positive `risk_multiplier` in both forms and local rejection of missing, null, zero, or negative multiplier values.
- [ ] 5.3 Test opaque identifier and ticker preservation, path-segment encoding, dot-only segments, closed body shape, and exact-decimal lexeme preservation.
- [ ] 5.4 Test exact decoding of both success DTOs and rejection of identifier mismatches, open/malformed objects, wrong types, invalid decimals, and undocumented `2xx`.
- [ ] 5.5 Test all four public error mappings, validation detail preservation, malformed envelopes, timeout, network failure, redirects, and undocumented statuses.
- [ ] 5.6 Assert every adapter invocation makes at most one HTTP request and every unconfirmed outcome fails closed.

## 6. ABI OpenAPI Conformance and Verification

- [ ] 6.1 Add a development/CI conformance check that reads the authoritative sibling `abi-entry-package-api-v1` OpenAPI document without introducing a production runtime dependency.
- [ ] 6.2 Verify the exact method, route, path parameters, closed request shape, nullable `desired_entry`, mandatory positive-string `risk_multiplier`, success union, decimal formats, and `400`/`415`/`422`/`500` mappings.
- [ ] 6.3 Run the focused client and fake-ABI contract tests.
- [ ] 6.4 Run the complete Runtime pytest suite, Ruff, mypy, and Python compilation checks.
- [ ] 6.5 Run strict OpenSpec change validation and repository-wide OpenSpec validation.
- [ ] 6.6 Review the diff to confirm no reconciliation, state mutation, persistence, orchestrator wiring, ABI implementation, or unrelated production/test behavior was added.
