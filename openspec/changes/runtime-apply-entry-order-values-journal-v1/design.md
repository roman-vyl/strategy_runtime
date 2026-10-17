## Context

Facts from the code on `main` (63bd7f5):

- The ABI applied response is decoded by a closed-field decoder
  (`runtime/abi/entry_package_codec.py`); an unknown key fails the response.
- The wire object `EntryPackageApplied` becomes `EntryAppliedConfirmation` in
  `entry_reconciliation_bridge/bridge.py`. The confirmation lives inside one
  `EntryReconciliationOrchestrator.execute` call; durable state keeps only the applied
  desired entry and `calculated_quantity`.
- The orchestrator has no journal port. The processing journal
  (`utility/processing_journal`) is best effort, append-only with `fsync`, and its
  envelope has no cycle id.
- The orchestrator already knows `strategy_instance_id`, `trade_cycle_id` and the
  confirmation; it does not know the bar.

## Decisions

### D1. Accept four optional fields

`EntryPackageApplied` and `EntryAppliedConfirmation` gain optional
`planned_entry_price`, `stop_loss`, `take_profit`, `quantity` (default `None`). The
decoder allows these keys, requires exact-decimal text for the price and quantity
fields, and allows `null` for `stop_loss` and `take_profit`. Any other unknown key still
fails the response. Responses without the fields decode as before. The values are not
added to `StrategyInstanceRuntimeState` and are not compared with the desired entry.

### D2. One journal event: `entry_package_applied`

After `execution_port.execute` returns an applied confirmation and before the state is
applied, the orchestrator appends one event through a new optional journal port method.
The event carries `strategy_instance_id` and `trade_cycle_id` in the envelope and
payload:

```json
"payload": {
  "planned_entry_price": "…",
  "stop_loss": "…" | null,
  "take_profit": "…" | null,
  "quantity": "…"
}
```

The values are exactly as received. If ABI sent none of them, no event is written.
Runtime adds no bar, desired entry or any computed value; the envelope `occurred_at` is
the time reference.

### D3. Envelope

`ProcessingJournalEvent` gains optional `trade_cycle_id`, serialized only when set.
`schema_version` becomes 3. The `live_entry_evaluated` event is unchanged.

### D4. Best effort

The port is optional. A journal failure is absorbed and counted as today and never
changes reconciliation, state saving or response handling.

## Risks / Trade-offs

- The event is written before the state step; a crash in between leaves an event for a
  cycle whose state step did not finish. Accepted, because the event records what ABI
  returned.
- Deploying ABI first would make this Runtime reject its responses; the order is part of
  the acceptance check.
