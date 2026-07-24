## 1. Event models

- [x] 1.1 Add the `utility/processing_journal` package.
- [x] 1.2 Add immutable versioned `ProcessingJournalEvent`.
- [x] 1.3 Add the committed-bar orchestration event-type enum.
- [x] 1.4 Add JSON-safe immutable payload and diagnostics handling.

## 2. JSONL implementation

- [x] 2.1 Add `JsonlProcessingJournal`.
- [x] 2.2 Implement every `ProcessingJournalPort` semantic method directly.
- [x] 2.3 Build event IDs, timestamps, envelopes, payloads, and diagnostics inside the module.
- [x] 2.4 Implement append-only UTF-8 JSONL writing with a process-local lock.
- [x] 2.5 Implement deterministic serialization, parent-directory creation, flush, and no truncation.
- [x] 2.6 Implement best-effort failure absorption at every public port method.
- [x] 2.7 Add fallback diagnostics that do not recursively depend on the journal.

## 3. Boundary cleanup

- [x] 3.1 Do not expose generic old `JournalEvent` factories to the orchestrator.
- [x] 3.2 Do not import old registry, activation, current-point, or `ReceiveClosedBar` event factories.
- [x] 3.3 Ensure raw deployment strategy specs are never serialized.
- [x] 3.4 Ensure journal failures cannot abort orchestrator processing.

## 4. Verification

- [x] 4.1 Test orchestration-start event serialization.
- [x] 4.2 Test orchestration-level failure event serialization.
- [x] 4.3 Test successful and failed strategy-cycle outcome events.
- [x] 4.4 Test completed aggregate event serialization.
- [x] 4.5 Test append-only behavior across restarts.
- [x] 4.6 Test concurrent process-local writes do not interleave lines.
- [x] 4.7 Test deterministic JSON serialization.
- [x] 4.8 Test filesystem and serialization failures are absorbed.
- [x] 4.9 Test no raw strategy specification leakage.
- [x] 4.10 Add architecture tests forbidding catalog, activation, selector, Engine, ABI, FastAPI, and superseded journal imports.
- [x] 4.11 Run the full test suite and static checks.
- [x] 4.12 Validate the OpenSpec change.
- [x] 4.13 Test the orchestration-level failure event and diagnostics.
- [x] 4.14 Test complete non-interleaved lines under concurrent in-process writes.
