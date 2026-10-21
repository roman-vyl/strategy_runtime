# processing-journal Specification

## Purpose
Define best-effort versioned append-only JSONL observability for committed-bar orchestration lifecycle and per-strategy dispatch outcomes.
## Requirements
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

### Requirement: Applied entry-order values are journaled

The processing journal MUST provide an `entry_package_applied` event, and Runtime MUST
emit one for every `entry_package_applied` response that carries the entry-order values,
with the received values verbatim, before the state is applied, without using them in
any decision or storing them in durable state.

#### Scenario: Applied response with values
- **WHEN** ABI returns `entry_package_applied` with the four values
- **THEN** one event is appended with `strategy_instance_id` in the envelope and `trade_cycle_id` plus the four values exactly as received in the payload

#### Scenario: No values in the response
- **WHEN** the applied response carries none of the four values, or the response is a cancel, absent or error outcome
- **THEN** no `entry_package_applied` event is appended

#### Scenario: Journal failure
- **WHEN** appending the event fails
- **THEN** the failure is absorbed and counted and reconciliation proceeds unchanged

### Requirement: The new event uses the existing journal mechanism

The `entry_package_applied` event MUST be written by the existing processing journal
adapter through the existing event envelope, carry `trade_cycle_id` in its payload, and
MUST NOT change the envelope fields, `schema_version`, or any other event type.

#### Scenario: Event shape
- **WHEN** an `entry_package_applied` event is written
- **THEN** the envelope has the same fields and `schema_version` as `live_entry_evaluated` and the payload holds `trade_cycle_id` and the four values

#### Scenario: Existing event type
- **WHEN** a `live_entry_evaluated` event is written
- **THEN** it is unchanged

### Requirement: Applied record links the evaluation and the order

The `entry_package_applied` payload MUST also contain `bar_open_time_ms` of the committed bar whose processing sent the apply, and `order_link_id` and `order_id` exactly as received from ABI or `null` when not received. Runtime MUST write the record when the applied response carries any of the four entry-order values or either identifier, and MUST NOT use these values in any decision or store them in durable state.

#### Scenario: Same bar as the evaluation
- **WHEN** a bar's processing journals `live_entry_evaluated` and then receives `entry_package_applied`
- **THEN** the `entry_package_applied` record has the same `strategy_instance_id` and `bar_open_time_ms` as that `live_entry_evaluated` event

#### Scenario: Identifiers received
- **WHEN** ABI returns `order_link_id` and `order_id`
- **THEN** the record carries them verbatim next to `trade_cycle_id` and the four values

#### Scenario: Identifiers not received
- **WHEN** ABI returns the four values without identifiers
- **THEN** the record is written with `order_link_id` and `order_id` equal to `null`

#### Scenario: Nothing received
- **WHEN** the applied response has none of the four values and no identifier, or the outcome is cancel, absent or error
- **THEN** no record is written

### Requirement: Every confirmed trade-cycle closure is journaled after the durable save
Runtime SHALL write `trade_cycle_closed` (schema version 2, `strategy_instance_id` in the envelope) with payload `trade_cycle_id`, `bar_open_time_ms`, `reason`, `order_id`, `order_link_id`, `parent_order_link_id`, taken verbatim from ABI's closure, only after the state without the cycle was durably saved. `bar_open_time_ms` SHALL be the committed bar on which Runtime learned of the closure, or `null` when it was learned by the pending-close resolver. The record SHALL NOT be used in any decision.

#### Scenario: Closure learned on a bar
- **WHEN** a bar ends a cycle by a closure or by a confirmed close carrying one
- **THEN** one record is written after the save with that bar's `bar_open_time_ms`

#### Scenario: Save failed
- **WHEN** saving the state without the cycle fails
- **THEN** no `trade_cycle_closed` record is written

### Requirement: Every Open Trade transition is journaled after the durable save
Runtime SHALL write `trade_cycle_opened` (schema version 2, `strategy_instance_id` in the envelope) with payload `trade_cycle_id`, `bar_open_time_ms`, `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id`, `entry_order_id`, only after the state with the newly frozen entry context was durably saved. The record SHALL mean the first confirmed execution of the cycle's entry order, a partial one included; `average_entry_price` SHALL be ABI's value at that observation, not a final entry price. `bar_open_time_ms` SHALL be the committed bar on which Runtime made the transition, or `null` on the recovery path. A write failure SHALL NOT raise into orchestration and SHALL NOT change Runtime state. The record SHALL NOT be used in any decision.

#### Scenario: Partial fill
- **WHEN** the transition is made from a partially filled entry order
- **THEN** the record is written with ABI's current `average_entry_price`

#### Scenario: Missing exchange order id
- **WHEN** ABI reported `entry_order_id: null`
- **THEN** the record carries `entry_order_id: null`

#### Scenario: Journal write fails
- **WHEN** appending the record fails
- **THEN** the failure counter grows, no exception reaches orchestration, and the saved state is unchanged

### Requirement: Open-trade evaluation event
The processing journal SHALL provide an `open_trade_evaluated` event (schema version 2, `strategy_instance_id` in the envelope) with payload `instrument`, `timeframe`, `bar_open_time_ms`, `trade_cycle_id`, `side`, `desired_protection` (`stop_price`, `take_price`) and `close_signal` (`active`, `reason`, `component_id`, `layer`). Prices SHALL be Engine's own wire text, unchanged; an absent `take_price` and absent close signal fields SHALL be JSON `null`. The payload SHALL NOT contain Engine diagnostics. A write failure SHALL NOT raise into orchestration and SHALL NOT change Runtime state.

#### Scenario: Short position with no take
- **WHEN** the event is written for a short position whose desired protection has no take price
- **THEN** the payload has `side: "short"` and `desired_protection.take_price: null`

#### Scenario: Journal write fails
- **WHEN** appending `open_trade_evaluated` fails
- **THEN** orchestration continues and the state is unchanged

### Requirement: Protection applied event
The processing journal SHALL provide a `protection_applied` event (schema version 2, `strategy_instance_id` in the envelope) with payload `trade_cycle_id`, `bar_open_time_ms`, `requested_protection` and `confirmed_protection` (each `{stop_price, take_price}`), `position_quantity`, `stop_order` and `take_order` (each `{order_id, trigger_price}`). Requested levels SHALL be the ones Runtime sent; confirmed levels, quantity and orders SHALL be exactly as ABI returned them. `take_price` SHALL be JSON `null` when absent while `take_order` is still present; nothing SHALL be hidden or substituted. A write failure SHALL NOT raise into orchestration and SHALL NOT change Runtime state.

#### Scenario: No take requested
- **WHEN** Runtime requested `take_price: null`
- **THEN** the record has `take_price: null` in both `requested_protection` and `confirmed_protection`, and `take_order` with the id and trigger price of the take order ABI actually keeps on the exchange

#### Scenario: Journal write fails
- **WHEN** appending `protection_applied` fails
- **THEN** position management continues and the confirmed protection is still applied to state

