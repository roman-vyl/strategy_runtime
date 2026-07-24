## Why

`CommittedBarOrchestrator` emits semantic lifecycle events for one committed bar and its per-strategy dispatch outcomes. This change introduces a processing-journal capability implementing `ProcessingJournalPort` directly for committed-bar orchestration. The capability owns semantic event construction, append-only JSONL persistence, bar and strategy-instance coordinates, and best-effort failure handling.

## What Changes

- Add semantic processing-journal event models for orchestration start, failure, per-cycle outcome, and completion.
- Add `JsonlProcessingJournal` implementing `ProcessingJournalPort` directly.
- Provide append-only UTF-8 JSONL writing, process-local locking, flush, and deterministic serialization.
- Provide a versioned event envelope containing committed-bar coordinates and, for per-cycle events, stable strategy-instance identity.
- Keep orchestration-specific event construction inside the journal capability.
- Define journal failure policy explicitly as best-effort at the port boundary.

## Capabilities

### New Capabilities

- `processing-journal`: Persists committed-bar orchestration lifecycle events as versioned append-only JSONL without affecting orchestration success.

### Modified Capabilities

None.

## Impact

- Provides the observability function required by `CommittedBarOrchestrator`.
- Journal infrastructure remains isolated from orchestration logic.
- No compatibility adapter for a removed journal boundary is introduced.
