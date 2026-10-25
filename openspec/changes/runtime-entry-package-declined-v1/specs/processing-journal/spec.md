## ADDED Requirements

### Requirement: Declined entry attempts are journaled
The processing journal MUST provide an `entry_package_declined` event, and
Runtime MUST emit exactly one for every declined `Apply`, after the durable
save, through the existing adapter and envelope.

#### Scenario: Event shape
- **WHEN** an `entry_package_declined` event is written
- **THEN** severity is `warning`, `strategy_instance_id` is in the envelope, and the payload is exactly `trade_cycle_id`, `bar_open_time_ms`, `risk_multiplier`, `decline_reason`, `decline_message`
- **AND** the envelope fields, `schema_version`, and every other event type are unchanged

#### Scenario: Declined Apply
- **WHEN** an `Apply` is declined by ABI
- **THEN** one `entry_package_declined` event is appended with the declined `trade_cycle_id`, the bar's `bar_open_time_ms`, the `risk_multiplier` that was sent, and ABI's `decline_reason` and `decline_message` verbatim

#### Scenario: No event for other outcomes
- **WHEN** the outcome is applied, absent, a public error, or a transport or protocol failure
- **THEN** no `entry_package_declined` event is appended

#### Scenario: Journal failure
- **WHEN** appending the event fails
- **THEN** the failure is absorbed and counted and reconciliation proceeds unchanged
