# strategy-operator-commands Specification

## Purpose
Operator commands that act on one strategy instance outside its own decisions: leave the open position, or cancel the waiting entry order. Both leave the strategy disabled.
## Requirements
### Requirement: Runtime closes a strategy's position on an operator command
Runtime SHALL expose `POST /v1/strategy-instances/{strategy_instance_id}/close-position` with an empty body. Under the instance's mutex it SHALL refuse unless the instance has a current trade cycle with a position ABI reports open and no recovery marker, then write `enabled=false`, save the `pending_close_recovery` marker, call the position-management `close_position` execution with the canonical full close, and answer `200` only after ABI's verified `PositionClosedConfirmation`. On that confirmation it SHALL clear the cycle and the marker in one save and journal `trade_cycle_closed` with the closure ABI proved. A success answers `200` with `strategy_instance_id`, `trade_cycle_id`, `enabled: false` and the closure `reason`.

#### Scenario: Position closed
- **WHEN** the instance is in a position and ABI confirms the close
- **THEN** the state has no current cycle and no marker, the file has `enabled: false`, `trade_cycle_closed` is journaled, and Runtime answers `200`

#### Scenario: No position
- **WHEN** the instance has no current cycle, or ABI reports no open position
- **THEN** Runtime answers `409` with reason `no_position` and changes nothing

#### Scenario: Recovery pending
- **WHEN** the instance has a pending entry-recovery or close-recovery marker
- **THEN** Runtime answers `409` with reason `recovery_pending` and makes no ABI close call

#### Scenario: Cycle ended by its own orders
- **WHEN** the resolver detects a closure of the cycle on its own stop or take
- **THEN** Runtime answers `409` with reason `cycle_not_settled` and does not close or apply it itself

#### Scenario: First fill not yet frozen
- **WHEN** ABI shows the position open but the cycle has no frozen executed-entry context
- **THEN** Runtime freezes the first fill and journals `trade_cycle_opened` exactly as bar processing does, then closes

#### Scenario: Close not confirmed
- **WHEN** the ABI close raises or returns no confirmation
- **THEN** the marker stays, `enabled` stays `false`, Runtime answers `502` with reason `abi_unavailable`, and the uncertain-state resolver finishes the close later

#### Scenario: Repeating the command
- **WHEN** the same command is sent again after a failure
- **THEN** it is decided afresh by the same rules and never closes more than the current position

### Requirement: Runtime cancels a strategy's resting entry order on an operator command
Runtime SHALL expose `POST /v1/strategy-instances/{strategy_instance_id}/cancel-entry-orders` with an empty body. Under the instance's mutex it SHALL run the same cancel step as a disable and then write `enabled=false`, even when the file already says `enabled: false`. A success answers `200` with `strategy_instance_id`, `enabled: false` and `cancelled_entry_order` (`true` when an order was cancelled, `false` when the instance had none).

#### Scenario: Entry order cancelled
- **WHEN** the instance has a resting entry order and ABI answers the corrective CANCEL with an exact `absent` for this instance and cycle
- **THEN** the state has no current cycle, `entry_cycle_ended` with reason `disabled` is journaled, the file has `enabled: false`, and Runtime answers `200` with `cancelled_entry_order: true`

#### Scenario: Nothing to cancel
- **WHEN** the instance has no current trade cycle
- **THEN** Runtime writes `enabled: false` and answers `200` with `cancelled_entry_order: false`

#### Scenario: Already disabled with an order left
- **WHEN** the file says `enabled: false` and a resting entry order exists
- **THEN** the order is cancelled as above

#### Scenario: Position open
- **WHEN** ABI reports an open position
- **THEN** Runtime answers `409` with reason `position_open` and changes nothing

#### Scenario: Cancel not confirmed or ABI unavailable
- **WHEN** the CANCEL is answered with anything but the exact `absent`, or ABI does not answer
- **THEN** Runtime answers `409` `cancel_not_confirmed` or `502` `abi_unavailable`, and state and file are unchanged

### Requirement: Operator commands share the instance's serialization and error vocabulary
Both commands SHALL be decided under the instance's keyed mutex with the same wait as the enabled control and answer `503` with reason `instance_busy` when it times out. They SHALL answer `404` for an id not in the catalog, `503` `not_ready` before startup readiness, `503` `catalog_unavailable`, `409` `file_changed` / `500` `write_failed` for file problems, with the same codes as the enabled control. No other method is allowed on these paths (`405`).

#### Scenario: Instance busy
- **WHEN** the instance is processing a bar and the mutex wait times out
- **THEN** Runtime answers `503` with reason `instance_busy` and changes nothing

#### Scenario: Unknown instance
- **WHEN** the id is not an accepted deployment
- **THEN** Runtime answers `404` and takes no mutex

#### Scenario: Wrong method
- **WHEN** a client sends `GET` to either path
- **THEN** Runtime answers `405`

