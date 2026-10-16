## ADDED Requirements

### Requirement: Every successful live-entry evaluation is journaled

The processing journal MUST provide a `live_entry_evaluated` event, and Runtime MUST
emit exactly one such event for every successful Strategy Engine `live-entry`
response, before entry reconciliation runs.

#### Scenario: Engine returns a desired entry
- **WHEN** Engine `live-entry` returns a non-null `desired_entry` for a strategy instance and target bar
- **THEN** the journal appends one `live_entry_evaluated` event with that `strategy_instance_id`, instrument, timeframe, `bar_open_time_ms` equal to the target bar, and `desired_entry` with exactly the decoded fields as exact decimal text

#### Scenario: Engine returns no entry
- **WHEN** Engine `live-entry` returns `desired_entry = null`
- **THEN** the journal appends one `live_entry_evaluated` event whose `desired_entry` is JSON `null`

#### Scenario: Later ABI step fails
- **WHEN** Engine `live-entry` succeeds and the following entry reconciliation or ABI call fails
- **THEN** the `live_entry_evaluated` event for that evaluation is still present

#### Scenario: No live-entry evaluation happened
- **WHEN** the bar is skipped because of a pending recovery marker, the instance is routed to open-trade, or Engine `live-entry` fails
- **THEN** no `live_entry_evaluated` event is appended for that instance and bar

#### Scenario: Same bar evaluated twice
- **WHEN** a duplicate committed-bar event causes a second successful evaluation of the same bar
- **THEN** a second `live_entry_evaluated` event with its own `event_id` is appended

## MODIFIED Requirements

### Requirement: Append-only deterministic JSONL serialization

The processing journal MUST append one complete JSON object per line using
deterministic key ordering and compact UTF-8 serialization without truncating
existing data, and MUST `flush` and `fsync` the file after each appended line.

#### Scenario: Runtime restarts
- **WHEN** the journal is reopened after existing events were written
- **THEN** new events are appended after existing lines
- **AND** previous lines remain unchanged

#### Scenario: Concurrent in-process writes
- **WHEN** multiple threads journal events concurrently through one journal instance
- **THEN** every event is written as one complete non-interleaved JSONL line

#### Scenario: Line is durable before the method returns
- **WHEN** a journal method returns normally after appending an event
- **THEN** the line has been flushed and fsynced

### Requirement: Journal is best effort

Journal serialization or filesystem failure, including an `fsync` failure, MUST NOT
abort committed-bar orchestration or change the outcome of the strategy cycle.

#### Scenario: Journal path is unavailable
- **WHEN** a semantic journal method cannot persist its event
- **THEN** the method absorbs the internal failure and returns normally
- **AND** reports the failure through a non-journal fallback diagnostic

#### Scenario: fsync fails
- **WHEN** `fsync` raises while appending a `live_entry_evaluated` event
- **THEN** the failure is absorbed and counted, and entry reconciliation proceeds unchanged
