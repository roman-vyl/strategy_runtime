## ADDED Requirements

### Requirement: Runtime sets a strategy's enabled state over HTTP
Runtime SHALL expose `PUT /v1/strategy-instances/{strategy_instance_id}/enabled` with a body of exactly `{"enabled": <boolean>}`. A success answers `200` with `{"strategy_instance_id", "enabled", "cancelled_entry_order"}`.

#### Scenario: Enable
- **WHEN** a disabled instance receives `{"enabled": true}`
- **THEN** Runtime stores the value and answers `200` with `enabled: true` and `cancelled_entry_order: false`
- **AND** Runtime makes no ABI call

#### Scenario: Already in the requested state
- **WHEN** the stored value already equals the requested one
- **THEN** Runtime answers `200` without writing and without an ABI call

#### Scenario: Unknown instance
- **WHEN** the id is not an accepted deployment in the catalog
- **THEN** Runtime answers `404`

#### Scenario: Bad body
- **WHEN** the body has other keys, a missing key or a non-boolean `enabled`
- **THEN** Runtime answers `422` and changes nothing

#### Scenario: Not ready
- **WHEN** Runtime is not ready
- **THEN** Runtime answers `503` with the not-ready body and changes nothing

### Requirement: Disable never leaves an order or a position unmanaged
Runtime SHALL decide a disable under the instance's mutex, against ABI, and SHALL change nothing on any non-`200` answer.

#### Scenario: Nothing open
- **WHEN** the instance has no current trade cycle
- **THEN** Runtime stores the value and answers `200` with `cancelled_entry_order: false`

#### Scenario: Position open
- **WHEN** the instance has a current trade cycle and ABI reports an open position
- **THEN** Runtime answers `409` with reason `position_open`
- **AND** the stored `enabled` stays true

#### Scenario: Recovery pending
- **WHEN** the instance has a pending entry-recovery or close-recovery marker
- **THEN** Runtime answers `409` with reason `recovery_pending` and makes no ABI call

#### Scenario: Cycle ended by its own orders
- **WHEN** the resolver detects a closure of the cycle
- **THEN** Runtime answers `409` with reason `cycle_not_settled` and does not apply the closure itself

#### Scenario: Entry order is cancelled
- **WHEN** the instance has a current trade cycle, no position is open, and the corrective CANCEL is answered with an exact `absent` for this instance and cycle
- **THEN** Runtime saves the state with no current trade cycle, stores the value, and answers `200` with `cancelled_entry_order: true`

#### Scenario: Cancel not confirmed
- **WHEN** the CANCEL is answered with anything other than that exact `absent`
- **THEN** Runtime answers `409` with reason `cancel_not_confirmed`, leaves state and the stored value unchanged

#### Scenario: ABI unavailable
- **WHEN** the ABI client raises an error during the resolver call or the CANCEL
- **THEN** Runtime answers `502` with reason `abi_unavailable` and changes nothing

#### Scenario: Instance busy
- **WHEN** a bar of the same instance is in flight and the mutex is not obtained within 30 seconds
- **THEN** Runtime answers `503` with reason `instance_busy` and changes nothing

### Requirement: Runtime stores one enabled value per strategy and reads the spec file's value once
Runtime SHALL keep one stored `enabled` value per accepted strategy instance. When the bar path or the enable route first meets an instance with no stored value, Runtime SHALL write the spec file's `enabled` as its stored value and SHALL NOT read the file's `enabled` again for that instance. Committed-bar selection and the strategy list SHALL use the stored value.

#### Scenario: First sight seeds from the file
- **WHEN** a committed bar selects an accepted deployment with no stored value and the file says `enabled: false`
- **THEN** Runtime stores `enabled: false` with source `file` and does not select the instance

#### Scenario: A later file edit changes nothing
- **WHEN** a stored value exists and the spec file's `enabled` is edited
- **THEN** selection and the list still use the stored value

#### Scenario: The list does not write
- **WHEN** the list route meets an instance with no stored value
- **THEN** it shows the file's value and writes nothing

#### Scenario: Value for a removed spec
- **WHEN** a stored value exists for an id that is no longer an accepted deployment
- **THEN** it is ignored

### Requirement: The stored value is durable and replayed at start
Runtime SHALL append each stored value (seeded or set by the route) to `enabled_store.jsonl` in the journal directory and SHALL flush it to disk before answering `200`. At start Runtime SHALL replay the file, the last line per instance winning.

#### Scenario: Survives a restart
- **WHEN** a strategy was disabled and Runtime restarts
- **THEN** the strategy is still stored as disabled

#### Scenario: Truncated final line
- **WHEN** the final line of the file is syntactically truncated
- **THEN** it is dropped and start continues

#### Scenario: Corrupt line
- **WHEN** any other line is not a valid record
- **THEN** startup fails and Runtime does not become ready

#### Scenario: Write failure
- **WHEN** the value cannot be appended
- **THEN** Runtime answers `500` and the stored value is unchanged
