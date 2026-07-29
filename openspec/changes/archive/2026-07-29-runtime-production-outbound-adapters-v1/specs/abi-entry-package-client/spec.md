## ADDED Requirements

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

## MODIFIED Requirements

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

### Requirement: Contract tests verify the implemented ABI contract
The future client layer SHALL include contract tests using a fake ABI and
conformance verification against the approved ABI OpenAPI document.

#### Scenario: Verify the raw outbound request
- **WHEN** fake ABI contract tests exercise present and absent requests
- **THEN** they assert the exact method, encoded route, content type, closed JSON body, nullable `desired_entry`, mandatory non-null `risk_multiplier`, opaque values, and decimal-string preservation

#### Scenario: Verify all response classes
- **WHEN** fake ABI emits both successes, all four public errors, mismatched identifiers, malformed payloads, obsolete `accepted_risk_multiplier` echoes, timeout, network failure, redirects, and undocumented statuses
- **THEN** tests assert the exact typed result or failure
- **AND** assert that no unconfirmed outcome becomes success

#### Scenario: Verify ABI OpenAPI conformance
- **WHEN** client contract verification reads the authoritative
  `abi-entry-package-api-v1` OpenAPI document
- **THEN** it confirms the exact method, route, nullable `desired_entry`, mandatory positive-string `risk_multiplier`, success union without `accepted_risk_multiplier`, closed DTOs, decimal formats, and `400`/`415`/`422`/`500` mappings
- **AND** verification fails if the authoritative document is missing or incompatible

#### Scenario: Keep verification out of production runtime
- **WHEN** the production client is built or invoked
- **THEN** it does not load the sibling repository or OpenAPI document at runtime