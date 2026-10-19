## ADDED Requirements

### Requirement: Every ABI-confirmed protection is journaled
For an `ApplyProtection` decision, the orchestrator SHALL write exactly one `protection_applied` event after ABI confirms the protection and before the confirmation is applied to state. `stop_price` and `take_price` SHALL come from ABI's confirmed protection, `stop_order` and `take_order` from ABI's `protection_orders`; `bar_open_time_ms` SHALL be the committed bar of the projection. No event SHALL be written for `NoOp`, `ClosePosition`, or when ABI does not confirm.

#### Scenario: Protection moved
- **WHEN** ABI confirms a new stop and take for the current cycle
- **THEN** one `protection_applied` event carries the cycle id, this bar's time, the confirmed prices and both protective orders' `order_id`, `trigger_price` and `quantity`

#### Scenario: ABI fails
- **WHEN** `apply_protection` raises
- **THEN** no `protection_applied` event is written

#### Scenario: Save fails after confirmation
- **WHEN** ABI confirmed, the event was written and the state save then fails
- **THEN** the event stays, and a repeated Apply on a later bar writes a second event
