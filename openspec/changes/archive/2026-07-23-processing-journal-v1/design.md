## Context

The new orchestrator calls semantic journal methods:

```text
orchestration_started
orchestration_failed
strategy_cycle_outcome
orchestration_completed
```

The journal owns translation of those calls into durable JSONL event records. The orchestrator must not construct journal envelopes, event IDs, timestamps, or JSON payloads.

## Goals / Non-Goals

**Goals:**

- Implement `ProcessingJournalPort` directly.
- Persist semantic committed-bar orchestration events as append-only JSONL.
- Keep event-envelope construction inside the journal module.
- Preserve committed-bar coordinates and stable strategy-instance identity without a trace or flow identifier.
- Make journal operations best-effort so observability failure does not stop trading orchestration.
- Expose internal diagnostics for journal write failures without throwing into the orchestrator.

**Non-Goals:**

- No trading-event taxonomy beyond the committed-bar orchestrator.
- No durable work queue or transaction log.
- No replay, deduplication, or recovery semantics.
- No registry, activation, selector, Engine, or ABI business logic.
- No generic journal API outside the semantic processing-journal port.

## Decisions

```text
CommittedBarOrchestrator
    → ProcessingJournalPort semantic method
    → JsonlProcessingJournal builds ProcessingJournalEvent
    → append one deterministic JSON line
```

### Keep the journal in one autonomous utility package

```text
src/strategy_runtime/utility/processing_journal/
├── __init__.py
├── models.py
└── jsonl_adapter.py
```

### Own the versioned event envelope

`ProcessingJournalEvent` is immutable and versioned. It conceptually contains:

```text
schema_version
event_id
event_type
occurred_at
source
strategy_instance_id?
severity
payload
diagnostics
```

Payload and diagnostics are recursively JSON-safe and immutable before serialization. Raw strategy specifications must not be copied into journal events.

### Map semantic port calls to event types

Minimum event types:

```text
committed_bar_orchestration_started
committed_bar_orchestration_failed
strategy_cycle_dispatch_succeeded
strategy_cycle_dispatch_failed
committed_bar_orchestration_completed
```

The journal maps `StrategyCycleDispatchOutcome` status to the corresponding per-cycle event type.

### Implement the consumer-owned semantic port directly

The capability directly implements the exact `ProcessingJournalPort` methods currently owned by the orchestrator package.

No generic `append(JournalEvent)` object is exposed to the orchestrator.

### Absorb internal failures at the port boundary

Every public `ProcessingJournalPort` method MUST absorb internal serialization or filesystem failures and return `None`, so journal unavailability cannot stop catalog loading, deployment selection, or strategy fan-out.

The implementation SHOULD report write failures through a fallback standard logger or in-memory diagnostic counter, but that mechanism must not recursively use the processing journal.

This policy preserves the useful behavior of the previous `ReceiveClosedBar._append_best_effort()` while moving it into the correct autonomous boundary.

### Append complete deterministic JSONL records

The implementation provides:

- append-only UTF-8 JSONL;
- one complete JSON object per line;
- process-local write locking;
- parent-directory creation;
- flush after every append;
- deterministic key ordering;
- generated event IDs and UTC timestamps;
- no file truncation on restart.

The capability does not expose generic event factories or accept raw deployment specifications.

### Preserve the processing-journal dependency boundary

Processing-journal packages must not import:

- filesystem deployment catalog;
- deployment selector;
- Strategy Engine or ABI clients;
- FastAPI;
- `ReceiveClosedBar` or unrelated application flows.

## Risks / Trade-offs

- [Best-effort persistence can lose observability events] → `failure_count` and fallback logging expose local failures without changing orchestration outcomes.
- [Process-local locking does not coordinate multiple processes] → The current Runtime owns one in-process writer; cross-process coordination is deferred.
- [Flush per event adds filesystem overhead] → Durable visibility and complete records are preferred for the current event volume.
