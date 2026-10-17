## Why

ABI is about to return, inside its existing responses, the physical state of one trade
cycle's own entry order (`cycle_execution_state`, ABI change
`abi-entry-order-observation-v1`). Runtime must (a) accept that optional field without
breaking its strict closed-field decoders, and (b) write what ABI returned into its own
processing journal `runtime.jsonl`, so history can show what Runtime wanted next to what
actually existed on Bybit for that `(strategy_instance_id, trade_cycle_id)`.

Runtime records facts it received. It does not store them in its durable state, does
not use them in decisions and knows nothing about who reads `runtime.jsonl`.

## What Changes

- Runtime's ABI clients accept an optional `cycle_execution_state` in the entry-package
  applied response and in the recovery-state `entry_order_live` and `position_open`
  responses, and an optional `executed_quantity` in the open-position
  `position_open: true` response. Decoders stay strict about every other field. Absent
  fields decode as `None`; responses without them behave exactly as today.
- Typed transient models carry the decoded values on the existing confirmation and
  response objects. They are not part of `StrategyInstanceRuntimeState` and are not
  persisted.
- A new processing-journal event `cycle_execution_state_observed` is appended whenever
  Runtime receives one of those ABI responses that carries physical data. The event
  carries `strategy_instance_id`, `trade_cycle_id`, which operation produced it, the
  applied desired entry where the response has one, and the received values verbatim.
- The journal envelope gains an optional top-level `trade_cycle_id` and its
  `schema_version` goes from 2 to 3. Existing `live_entry_evaluated` events keep their
  shape.
- Journal ports are added (optional, best effort) to the entry-reconciliation
  orchestrator, the uncertain-exchange-state resolver and the open-position resolution
  path.

## Out of Scope

State-file changes, using the data in any decision, per-fill or fee data, child
stop-loss/take-profit orders, protection, management and close events, cancel and
cycle-lifecycle events, `evaluation_event_id`, any reader of `runtime.jsonl`, ABI
changes, polling or additional ABI requests, rotation of the journal.

## Capabilities

### Modified Capabilities

- `processing-journal`, `abi-entry-package-client`, `abi-entry-cycle-recovery-client`,
  `abi-open-position-lookup-client`.

## Impact

- `infrastructure/abi/entry_package_codec.py`, `entry_cycle_recovery_codec.py`,
  `open_position_codec.py`, `runtime/entry_reconciliation/models.py`,
  `runtime/abi/entry_cycle_recovery_models.py`, `runtime/open_position/models.py`,
  entry-reconciliation orchestrator, resolver, open-position resolver, processing
  journal models/adapter/ports, bootstrap wiring, tests.
- The durable state file and its codec are untouched.
- Deploy order: this change first, then the ABI change (ABI responses with the new field
  are rejected by older Runtime).
