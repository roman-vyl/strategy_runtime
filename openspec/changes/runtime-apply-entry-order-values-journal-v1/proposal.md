## Why

ABI is about to add four values of the trade cycle's own entry order to its
`entry_package_applied` response (ABI change `abi-apply-entry-order-values-v1`):
`trigger_price`, `stop_loss`, `take_profit`, `quantity`. Runtime has to accept
them without breaking its strict response decoder, and write them to its own
processing journal `runtime.jsonl`, so history can show what was actually placed.

Runtime records what it received. It does not store the values in durable state and
does not use them in any decision.

## What Changes

- The ABI entry-package client accepts the four optional fields in
  `entry_package_applied`, decodes them strictly, and carries them on the existing
  applied confirmation as optional values.
- After a successful apply, the entry-reconciliation orchestrator appends one
  `entry_package_applied` event to `runtime.jsonl` with `strategy_instance_id`,
  `trade_cycle_id` and the four values exactly as received.
- The journal envelope gains an optional top-level `trade_cycle_id`. `schema_version`
  stays as it is.

## Out of Scope

Durable state changes, any decision based on the values, cancel, recovery,
open-position, protection and close responses, order id and status, fills, any reader
of `runtime.jsonl`, any ABI change.

## Capabilities

### Modified Capabilities

- `abi-entry-package-client`, `processing-journal`.

## Impact

- `runtime/abi/entry_package_models.py`, `runtime/abi/entry_package_codec.py`,
  `runtime/entry_reconciliation/models.py`, `entry_reconciliation_bridge/bridge.py`,
  `entry_reconciliation_orchestrator/orchestrator.py`, processing journal models,
  adapter and port, bootstrap wiring, tests.
- The durable state file and its codec are untouched.
- Deploy order: this change before the ABI change (older Runtime rejects the new keys).
