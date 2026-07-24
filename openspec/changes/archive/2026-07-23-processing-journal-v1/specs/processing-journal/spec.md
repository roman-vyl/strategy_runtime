## ADDED Requirements

### Requirement: Semantic committed-bar processing journal

The Runtime MUST provide a processing journal implementing the committed-bar orchestrator's semantic journal port.

#### Scenario: Orchestration starts

- **WHEN** the orchestrator calls `orchestration_started`
- **THEN** the journal appends one versioned `committed_bar_orchestration_started` JSONL event without requiring a propagated trace or flow identifier

#### Scenario: Upstream preparation fails

- **WHEN** the orchestrator calls `orchestration_failed` with a preparation stage and exception
- **THEN** the journal appends one `committed_bar_orchestration_failed` event
- **AND** records the stage in payload and error type and message in diagnostics

#### Scenario: One strategy-cycle dispatch completes

- **WHEN** the orchestrator reports a strategy-cycle outcome
- **THEN** the journal appends a success or failure event containing the stable deployment identity

#### Scenario: Orchestration completes

- **WHEN** the orchestrator reports its aggregate result
- **THEN** the journal appends one completion event containing aggregate counts

### Requirement: Append-only deterministic JSONL serialization

The processing journal MUST append one complete JSON object per line using deterministic key ordering and compact UTF-8 serialization without truncating existing data.

#### Scenario: Runtime restarts

- **WHEN** the journal is reopened after existing events were written
- **THEN** new events are appended after existing lines
- **AND** previous lines remain unchanged

#### Scenario: Concurrent in-process writes

- **WHEN** multiple threads journal events concurrently through one journal instance
- **THEN** every event is written as one complete non-interleaved JSONL line

### Requirement: Journal is best effort

Journal serialization or filesystem failure MUST NOT abort committed-bar orchestration.

#### Scenario: Journal path is unavailable

- **WHEN** a semantic journal method cannot persist its event
- **THEN** the method absorbs the internal failure and returns normally
- **AND** reports the failure through a non-journal fallback diagnostic

### Requirement: Journal owns event envelopes

The orchestrator MUST NOT construct journal event IDs, timestamps, envelopes, or JSON payloads.

#### Scenario: Semantic method is invoked

- **WHEN** the journal receives orchestration inputs
- **THEN** it constructs the versioned event internally

### Requirement: Journal event envelope is explicit

Every persisted event SHALL contain `schema_version`, `event_id`, `event_type`, `occurred_at`, `source`, `severity`, `payload`, and `diagnostics`.

#### Scenario: Bar-scoped event is constructed

- **WHEN** the journal constructs any committed-bar orchestration event
- **THEN** payload contains `instrument`, `timeframe`, and `open_time_ms`
- **AND** no trace or flow identifier is required

#### Scenario: Per-cycle event is constructed

- **WHEN** the journal constructs a successful or failed strategy-cycle dispatch event
- **THEN** the top-level event contains the outcome `strategy_instance_id`
- **AND** payload contains the outcome status

#### Scenario: Aggregate completion is constructed

- **WHEN** the journal constructs `committed_bar_orchestration_completed`
- **THEN** payload contains selected, attempted, succeeded, and failed counts
- **AND** severity is `info` when no dispatch failed and `warning` otherwise

### Requirement: Sensitive deployment content is excluded

The processing journal MUST NOT serialize complete raw strategy specifications.

#### Scenario: Per-deployment outcome is recorded

- **WHEN** one strategy-cycle outcome is journaled
- **THEN** the event may contain stable identity and technical outcome fields
- **AND** does not contain the raw deployment specification

### Requirement: Direct orchestrator port conformance

`JsonlProcessingJournal` MUST implement `ProcessingJournalPort` directly without
a compatibility adapter for a removed journal boundary.

#### Scenario: Direct semantic implementation

- **WHEN** `JsonlProcessingJournal` is supplied to `CommittedBarOrchestrator`
- **THEN** it satisfies every `ProcessingJournalPort` semantic method directly
- **AND** no compatibility adapter or generic journal port is required
