## Context

Facts from the code on `main` (63bd7f5):

- The ABI applied response is decoded by a closed-field decoder
  (`runtime/abi/entry_package_codec.py`); an unknown key fails the response.
- The wire object `EntryPackageApplied` becomes `EntryAppliedConfirmation` in
  `entry_reconciliation_bridge/bridge.py`. The confirmation lives inside one
  `EntryReconciliationOrchestrator.execute` call; durable state keeps only the applied
  desired entry and `calculated_quantity`.
- Journal writing today: one `JsonlProcessingJournal` instance (bootstrap `application.py`)
  serves two consumer-owned ports. `ProcessingJournalPort` is used by
  `CommittedBarOrchestrator` for bar-level events (`orchestration_*`,
  `strategy_cycle_dispatch_succeeded/failed`), which have no access to ABI responses.
  `LiveEntryEvaluationJournalPort` (`runtime/orchestrator/ports.py`) is an optional
  constructor argument of `StrategyRuntimeOrchestrator`, implemented by one adapter
  method `live_entry_evaluated(...)` that calls the private `_record`. Identity and index
  fields such as `bar_open_time_ms` travel in the payload; only `strategy_instance_id`
  is an envelope field.
- `EntryReconciliationOrchestrator.execute` returns only the state, so the confirmation
  never reaches `StrategyRuntimeOrchestrator`, which holds the existing port.
- The orchestrator already knows `strategy_instance_id`, `trade_cycle_id` and the
  confirmation; it does not know the bar.

## Decisions

### D1. Accept four optional fields

`EntryPackageApplied` and `EntryAppliedConfirmation` gain optional
`trigger_price`, `stop_loss`, `take_profit`, `quantity` (default `None`). The
decoder allows these keys, requires exact-decimal text for the price and quantity
fields, and allows `null` for `stop_loss` and `take_profit`. Any other unknown key still
fails the response. Responses without the fields decode as before. The values are not
added to `StrategyInstanceRuntimeState` and are not compared with the desired entry.

### D2. Same journal path as `live_entry_evaluated`

The new record uses the existing mechanism, not a new one:

- a new member `ENTRY_PACKAGE_APPLIED` in `ProcessingJournalEventType`;
- one method on the existing adapter `JsonlProcessingJournal` that calls the existing
  `_record`;
- a small consumer-owned Protocol in `entry_reconciliation_orchestrator/ports.py` (same
  convention as `LiveEntryEvaluationJournalPort`), passed as an optional constructor
  argument to `EntryReconciliationOrchestrator` and wired in `bootstrap/application.py`
  with the same `journal` instance.

The call sits in `EntryReconciliationOrchestrator.execute`, after `execution_port.execute`
returns an applied confirmation and before the state is applied, because that is the only
place that holds the confirmation together with `strategy_instance_id` and
`trade_cycle_id`. Passing the confirmation up to `StrategyRuntimeOrchestrator` would
change the return type of `execute` and every caller, so it is not done. The bar-level
`strategy_cycle_dispatch_*` events are emitted by `CommittedBarOrchestrator` after
dispatch with no access to the ABI response, so they cannot carry these values.

The event is written with the existing envelope and no new field:

```json
"strategy_instance_id": "…",
"payload": {
  "trade_cycle_id": "…",
  "trigger_price": "…",
  "stop_loss": "…" | null,
  "take_profit": "…" | null,
  "quantity": "…"
}
```

`trade_cycle_id` goes in the payload, as `bar_open_time_ms` does for
`live_entry_evaluated`. The values are exactly as received. If ABI sent none of them, no
event is written. The envelope `occurred_at` is the time reference; no bar, desired entry
or computed value is added.

### D3. No change to the journal envelope or version

`ProcessingJournalEvent`, `_record`, `source` and `schema_version` stay as they are. The
processing-journal spec only requires that every event carries `schema_version`; it
defines no rule that a new event type needs a new version, and no code dispatches on it.

### D4. Best effort

The port is optional. A journal failure is absorbed and counted as today and never
changes reconciliation, state saving or response handling.

## Risks / Trade-offs

- The event is written before the state step; a crash in between leaves an event for a
  cycle whose state step did not finish. Accepted, because the event records what ABI
  returned.
- Deploying ABI first would make this Runtime reject its responses; the order is part of
  the acceptance check.
