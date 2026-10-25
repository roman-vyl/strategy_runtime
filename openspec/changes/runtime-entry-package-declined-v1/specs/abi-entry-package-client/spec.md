## ADDED Requirements

### Requirement: Runtime decodes the declined acknowledgement of an APPLY
The Runtime client SHALL accept a third closed success DTO, HTTP `200` with
status `entry_package_declined`, only as the answer to a request with a
non-null `desired_entry`, and SHALL return it as `EntryPackageDeclined`
without interpreting the reason.

#### Scenario: Declined body shape
- **WHEN** a declined body is decoded
- **THEN** it has exactly `strategy_instance_id`, `trade_cycle_id`, `status`, `decline_reason`, and `decline_message`
- **AND** `decline_reason` is 1 to 64 characters from `[a-z0-9_]` starting with a letter
- **AND** `decline_message` is a non-empty string

#### Scenario: Decode declined acknowledgement
- **WHEN** a request with a non-null `desired_entry` receives HTTP `200` with exactly the five declined fields
- **AND** both identifiers equal the request identifiers and both strings satisfy their shape
- **THEN** Runtime returns `EntryPackageDeclined` with the exact `decline_reason` and `decline_message`

#### Scenario: Unknown reason code is still a valid declined answer
- **WHEN** `decline_reason` is a well-formed code Runtime has never seen
- **THEN** Runtime returns `EntryPackageDeclined` unchanged

#### Scenario: Reject a malformed declined body
- **WHEN** a declined body has a missing or unknown field, a non-string or badly shaped `decline_reason`, an empty or non-string `decline_message`, or an identifier that differs from the request
- **THEN** Runtime reports `AbiEntryPackageProtocolError`

#### Scenario: Reject declined for a CANCEL request
- **WHEN** a request with `desired_entry: null` receives a declined body
- **THEN** Runtime reports `AbiEntryPackageProtocolError`
- **AND** the existing failure path for that request is unchanged

#### Scenario: Other answers are unchanged
- **WHEN** ABI returns `entry_package_applied`, `entry_package_absent`, or any public error
- **THEN** Runtime decodes it exactly as before this change
