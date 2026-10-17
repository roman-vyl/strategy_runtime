## Context

Audit 2026-10-17 (thread "Trade Observatory"), `main` 63bd7f5:

- ABI response decoders are closed-field (`_require_exact_fields` in
  `entry_package_codec.py`, `entry_cycle_recovery_codec.py`, `open_position_codec.py`):
  an unknown key fails the call. Evolution must be two-step.
- Persisted state keeps only desired entry and quantity per cycle; first fill is frozen
  from `first_fill_at_ms`. `average_entry_price` from open-position is used for
  nothing durable.
- The processing journal (`utility/processing_journal`) writes
  `ProcessingJournalEvent(schema_version, event_id, event_type, occurred_at, source,
  severity, payload, diagnostics, strategy_instance_id)` best effort with `fsync`. Only
  the bar orchestrator has a journal port (`LiveEntryEvaluationJournalPort`); the
  entry-reconciliation orchestrator, the resolver and the open-position resolver have none.
- Entry reconciliation never knows the bar (`bar_open_time_ms` exists only in the
  bar orchestrator); the resolver runs outside any bar.

## Goals / Non-Goals

Goals: accept the new optional ABI data; append it to `runtime.jsonl` as received.
Non-goals: see proposal.

## Decisions

### D1. Transient typed models, no state change

A frozen `CycleExecutionState` model (`entry_order` and optional `executed_quantity`,
`average_entry_price`, mirroring ABI D1) is attached as an optional field with default
`None` to `EntryAppliedConfirmation`, `EntryOrderLiveRecoveryState` and
`PositionOpenRecoveryState`; `OpenPositionLookupResponse` gains optional
`executed_quantity`. Nothing in `StrategyInstanceRuntimeState` changes. All decimals stay
exact-decimal text as received. Existing equality-based checks use named fields and are
unaffected; tests cover this.

### D2. Decoders accept the field strictly

The allowed key sets gain `cycle_execution_state` / `executed_quantity`; their inner
objects are decoded with their own closed-field check (exact keys, string types,
nullable `stop_loss`/`take_profit`). A malformed inner object fails the response decode
like any other malformed response today. Absent means `None`.

### D3. One journal event: `cycle_execution_state_observed`

Appended when a received ABI response carries physical data, with
`strategy_instance_id`, `trade_cycle_id` and:

```json
"payload": {
  "source_operation": "entry_package_applied | recovery_state | open_position",
  "applied_desired_entry": { … } | null,
  "cycle_execution_state": { "entry_order": { … } | null,
                              "executed_quantity": "…" | null,
                              "average_entry_price": "…" | null }
}
```

`applied_desired_entry` is present for the applied and recovery responses (they carry
it) and `null` for open-position. For open-position only the execution fields exist; its
`entry_order` is `null`. Values are exactly as received. Runtime does not compute,
merge or infer. No `bar_open_time_ms` is written because the emitting code paths do not
have a bar; the envelope `occurred_at` is the time reference.

### D4. Emission points

- Entry-reconciliation orchestrator: after `execution_port.execute` returns an applied
  confirmation, before state application.
- Resolver: when a `recovery-state` response of `entry_order_live` or `position_open`
  carries the field, once per resolution attempt.
- Open-position: when `position_open` is true and `executed_quantity` is present, on
  every lookup (once per bar while a position is open). Repetition is accepted; readers
  deduplicate if they need to.
No event for cancel, absent, terminal or error responses.

### D5. Envelope: optional `trade_cycle_id`, schema_version 3

`ProcessingJournalEvent` gains optional `trade_cycle_id` (serialized only when set).
`schema_version` becomes 3 for all new events; `live_entry_evaluated` payload is
unchanged. Readers that handle version 2 keep working for those events.

### D6. Best effort and independence

New ports are optional. A journal failure is absorbed and counted exactly as today and
never changes orchestration, state or the response handling. Runtime writes the event
only from data in its own ABI response objects.

## Open question for the owner (not decided here)

When ABI confirms cancellation (`entry_package_absent`), nothing physical is returned
today, so V1 records no event for it. A reader that needs "this cycle's order ended"
must get it from a later change.

## Risks / Trade-offs

- The event is written before state is saved; a crash between the two leaves an
  observation for a cycle whose state step did not complete. Accepted; the cycle id and
  resolver recovery still reconcile reality.
- Per-bar open-position events grow the file; no rotation (unchanged from today).
- Deploying ABI first would make Runtime reject its responses; D5 ordering and the
  acceptance check below guard this.
