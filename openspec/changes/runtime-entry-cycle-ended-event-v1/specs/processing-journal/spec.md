## ADDED Requirements

### Requirement: Ended entry cycles are journaled
The processing journal MUST provide an `entry_cycle_ended` event, and Runtime MUST emit exactly one for every durable state change that removes a current trade cycle which has no frozen executed-entry context, after the durable save, through the existing adapter and envelope.

#### Scenario: Event shape
- **WHEN** an `entry_cycle_ended` event is written
- **THEN** `strategy_instance_id` is in the envelope and the payload is exactly `trade_cycle_id`, `bar_open_time_ms` and `reason`
- **AND** the envelope fields, `schema_version` and every other event type are unchanged

#### Scenario: Confirmed cancel in bar processing
- **WHEN** a CANCEL is confirmed absent during bar processing, alone or as the first step of a Replace
- **THEN** one event with `reason: "cancelled"` and the bar's `bar_open_time_ms` is appended

#### Scenario: Disable cancels the entry order
- **WHEN** enabled-control removes the cycle after a confirmed exact absence
- **THEN** one event with `reason: "disabled"` and `bar_open_time_ms: null` is appended

#### Scenario: Resolver ends the cycle
- **WHEN** the uncertain-state resolver clears a cycle because the entry is terminal without a fill, or because its corrective CANCEL returned exact formal absence
- **THEN** one event with `reason: "terminal_without_fill"` or `"exact_absent"` and `bar_open_time_ms: null` is appended

#### Scenario: No event for other changes
- **WHEN** a cycle is closed after a fill, an entry is applied, a recovery marker changes without removing a cycle, or a removal fails
- **THEN** no `entry_cycle_ended` event is appended

#### Scenario: Journal failure
- **WHEN** appending the event fails
- **THEN** the failure is absorbed and counted and the state change stands
