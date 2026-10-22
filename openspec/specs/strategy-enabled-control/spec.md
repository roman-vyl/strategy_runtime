# strategy-enabled-control Specification

## Purpose
Runtime changes the `enabled` field of one deployment file over HTTP, safely: a strategy with an open position is never disabled, a resting entry order is cancelled through ABI first, and the file is replaced atomically. The deployment file stays the only source of truth for `enabled`.
## Requirements
### Requirement: Runtime sets a strategy's enabled state over HTTP
Runtime SHALL expose `PUT /v1/strategy-instances/{strategy_instance_id}/enabled` with a body of exactly `{"enabled": <boolean>}`. A success answers `200` with `{"strategy_instance_id", "enabled", "cancelled_entry_order"}`.

#### Scenario: Enable
- **WHEN** a disabled instance receives `{"enabled": true}`
- **THEN** Runtime writes the file and answers `200` with `enabled: true` and `cancelled_entry_order: false`
- **AND** Runtime makes no ABI call

#### Scenario: Already in the requested state
- **WHEN** the file's `enabled` already equals the requested one
- **THEN** Runtime answers `200` without writing and without an ABI call

#### Scenario: Unknown instance
- **WHEN** the id is not an accepted deployment in the catalog
- **THEN** Runtime answers `404`

#### Scenario: Bad body
- **WHEN** the body has other keys, a missing key or a non-boolean `enabled`
- **THEN** Runtime answers `400` and changes nothing

#### Scenario: Not ready
- **WHEN** Runtime is not ready
- **THEN** Runtime answers `503` with the not-ready body and changes nothing

### Requirement: Disable never leaves an order or a position unmanaged
Runtime SHALL decide a disable under the instance's mutex, against ABI, and SHALL change nothing (state and file) on any non-`200` answer. The file SHALL be written after every check and exchange action.

#### Scenario: Nothing open
- **WHEN** the instance has no current trade cycle
- **THEN** Runtime writes the file and answers `200` with `cancelled_entry_order: false`

#### Scenario: Position open
- **WHEN** the instance has a current trade cycle and ABI reports an open position
- **THEN** Runtime answers `409` with reason `position_open`
- **AND** the file's `enabled` stays true

#### Scenario: Recovery pending
- **WHEN** the instance has a pending entry-recovery or close-recovery marker
- **THEN** Runtime answers `409` with reason `recovery_pending` and makes no ABI call

#### Scenario: Cycle ended by its own orders
- **WHEN** the resolver detects a closure of the cycle
- **THEN** Runtime answers `409` with reason `cycle_not_settled` and does not apply the closure itself

#### Scenario: Entry order is cancelled
- **WHEN** the instance has a current trade cycle, no position is open, and the corrective CANCEL is answered with an exact `absent` for this instance and cycle
- **THEN** Runtime saves the state with no current trade cycle, writes the file, and answers `200` with `cancelled_entry_order: true`

#### Scenario: Cancel not confirmed
- **WHEN** the CANCEL is answered with anything other than that exact `absent`
- **THEN** Runtime answers `409` with reason `cancel_not_confirmed`, leaves state and the file unchanged

#### Scenario: ABI unavailable
- **WHEN** the ABI client raises an error during the resolver call or the CANCEL
- **THEN** Runtime answers `502` with reason `abi_unavailable` and changes nothing

#### Scenario: Instance busy
- **WHEN** a bar of the same instance is in flight and the mutex is not obtained within 30 seconds
- **THEN** Runtime answers `503` with reason `instance_busy` and changes nothing

### Requirement: The deployment file is the only source of truth for enabled
Runtime SHALL keep no separate record of `enabled`. Bar selection, the strategy list and a Runtime restart SHALL use the `enabled` value in the deployment file.

#### Scenario: Survives a restart
- **WHEN** a strategy was disabled through the route and Runtime restarts
- **THEN** the file still says `enabled: false` and the strategy is not selected

#### Scenario: A manual edit takes effect
- **WHEN** the file's `enabled` is edited by hand and the next bar or list request arrives
- **THEN** selection and the list use the edited value

### Requirement: The enabled change replaces the deployment file atomically and changes only enabled
Runtime SHALL change `enabled` by writing the complete new document to a hidden temporary file in the same directory, flushing it to disk, and replacing the original with it. The new document SHALL equal the old one except for `enabled`, including other keys and their order. Runtime SHALL refuse the change, leaving the original file byte-identical and removing the temporary file, when the derived `strategy_instance_id` of the new document differs from the requested one, or when the original file's content changed between reading it and replacing it.

#### Scenario: Only enabled changes
- **WHEN** a disable succeeds
- **THEN** the replaced file differs from the original only in the value of `enabled`
- **AND** its derived `strategy_instance_id` is unchanged

#### Scenario: Temporary file is invisible
- **WHEN** the replacement is in progress
- **THEN** the catalog snapshot contains no entry for the temporary file

#### Scenario: Identity would change
- **WHEN** the new document would derive a different `strategy_instance_id`
- **THEN** Runtime answers `500` with reason `identity_changed` and writes nothing

#### Scenario: File changed since it was read
- **WHEN** the file content differs from what Runtime read before the replacement
- **THEN** Runtime answers `409` with reason `file_changed` and writes nothing

#### Scenario: Write failure
- **WHEN** the temporary file cannot be written or the replacement fails
- **THEN** Runtime answers `500` and the original file is unchanged and whole

#### Scenario: Duplicate or invalid file
- **WHEN** the instance id belongs to a duplicate identity or the file is not accepted by the catalog
- **THEN** Runtime writes nothing

