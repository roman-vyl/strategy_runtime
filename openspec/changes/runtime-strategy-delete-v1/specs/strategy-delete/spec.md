## ADDED Requirements

### Requirement: Runtime deletes a disabled strategy over HTTP by moving its file to the trash
Runtime SHALL expose `DELETE /v1/strategy-instances/{strategy_instance_id}` with no body. A success answers `200` with `{"strategy_instance_id", "deleted": true, "cancelled_entry_order", "trash_file"}` and SHALL have moved the strategy's deployment file to the hidden subdirectory `.deleted/` of the specs directory under the name `<stem>.<UTC time>.json`, without changing its content. Runtime SHALL NOT erase the file. A refusal answers with a body `{"status":"delete_refused","reason":<code>}`.

#### Scenario: Delete a disabled idle strategy
- **WHEN** an instance whose file says `enabled: false` and that has no current trade cycle receives the request
- **THEN** Runtime moves the file to `.deleted/` and answers `200` with `deleted: true` and `cancelled_entry_order: false`
- **AND** Runtime makes no ABI call

#### Scenario: The strategy leaves the catalog
- **WHEN** the file was moved
- **THEN** the next list request and the next bar do not contain the instance
- **AND** a repeated request for the same id answers `404` with reason `strategy_instance_not_found`

#### Scenario: Restore by hand
- **WHEN** the moved file is put back into the specs directory
- **THEN** the catalog lists the strategy again with the same identity

#### Scenario: Not ready
- **WHEN** Runtime is not ready
- **THEN** Runtime answers `503` with the not-ready body and changes nothing

### Requirement: Only a disabled strategy can be deleted
Runtime SHALL refuse the delete with `409` and reason `still_enabled` when the file's `enabled` is true, before any ABI call, and SHALL change nothing.

#### Scenario: Enabled strategy
- **WHEN** the file says `enabled: true`
- **THEN** Runtime answers `409` with reason `still_enabled`, makes no ABI call and leaves state and file unchanged

### Requirement: Delete never leaves an order or a position unmanaged
A strategy switched off through the enabled route has no recovery marker and no trade cycle; for it Runtime SHALL make no ABI call when deleting. As a safety net against a hand-edited file or an inconsistent legacy state, Runtime SHALL still repeat the disable's checks under the instance's mutex, against ABI, before it moves the file. On a non-`200` answer Runtime SHALL leave the file in place and unchanged and SHALL leave the state unchanged, except that after a confirmed cancel of an entry order the state has no current trade cycle. The file SHALL move after every check and exchange action.

#### Scenario: Normal path after a disable
- **WHEN** a strategy was switched off through the enabled route and is then deleted
- **THEN** its state has no recovery marker and no current trade cycle, Runtime makes no ABI call and moves the file

#### Scenario: Position open
- **WHEN** the instance has a current trade cycle and ABI reports an open position
- **THEN** Runtime answers `409` with reason `position_open` and leaves the file in place

#### Scenario: Recovery pending
- **WHEN** the instance has a pending entry-recovery or close-recovery marker
- **THEN** Runtime answers `409` with reason `recovery_pending` and makes no ABI call

#### Scenario: Cycle ended by its own orders
- **WHEN** the resolver detects a closure of the cycle
- **THEN** Runtime answers `409` with reason `cycle_not_settled` and does not apply the closure itself

#### Scenario: Entry order is cancelled
- **WHEN** the instance has a current trade cycle, no position is open, and the corrective CANCEL is answered with an exact `absent` for this instance and cycle
- **THEN** Runtime saves the state with no current trade cycle, moves the file, and answers `200` with `cancelled_entry_order: true`

#### Scenario: Cancel not confirmed
- **WHEN** the CANCEL is answered with anything other than that exact `absent`
- **THEN** Runtime answers `409` with reason `cancel_not_confirmed` and leaves state and file unchanged

#### Scenario: ABI unavailable
- **WHEN** the ABI client raises an error during the resolver call or the CANCEL
- **THEN** Runtime answers `502` with reason `abi_unavailable` and changes nothing

#### Scenario: Move fails after a cancel
- **WHEN** an inconsistent state had a current trade cycle, the cancel was confirmed and the file then cannot be moved (`file_changed`, `trash_name_taken` or `move_failed`)
- **THEN** Runtime answers with that reason, the file stays in place unchanged, the state has no current trade cycle, and a repeated request makes no ABI call

#### Scenario: Instance busy
- **WHEN** a bar of the same instance is in flight and the mutex is not obtained within 30 seconds
- **THEN** Runtime answers `503` with reason `instance_busy` and changes nothing

### Requirement: The trash move is safe and does not overwrite
Runtime SHALL move the file by linking it into `.deleted/` and then removing the original, creating `.deleted/` when it is missing, and SHALL refuse the delete, leaving the original byte-identical in place and no copy in the trash (the state keeps whatever a confirmed cancel already changed), when the file's content changed between reading it and moving it, when a file of the target name already exists, or when the move fails.

#### Scenario: File changed since it was read
- **WHEN** the file content differs from what Runtime read before the move
- **THEN** Runtime answers `409` with reason `file_changed` and moves nothing

#### Scenario: Target name taken
- **WHEN** a file with the target trash name already exists
- **THEN** Runtime answers `409` with reason `trash_name_taken` and moves nothing

#### Scenario: Move failure
- **WHEN** the trash directory cannot be created, the link fails or removing the original fails
- **THEN** Runtime answers `500` with reason `move_failed`, the original stays whole in place and no copy remains in the trash

#### Scenario: Unknown, duplicate or invalid
- **WHEN** the id is not an accepted deployment of the catalog, or belongs to a duplicate identity
- **THEN** Runtime answers `404` with reason `strategy_instance_not_found` and creates no mutex entry

#### Scenario: Catalog unreadable
- **WHEN** the catalog directory cannot be scanned
- **THEN** Runtime answers `503` with reason `catalog_unavailable` and changes nothing

### Requirement: State and history stay after a delete
Runtime SHALL NOT change the strategy-instance state store (other than clearing the current trade cycle of a cancelled entry order) and SHALL NOT change the Journal when it deletes a strategy.

#### Scenario: State record stays
- **WHEN** a strategy was deleted
- **THEN** its state record remains in the store, has no recovery marker, and the recovery workers skip it
