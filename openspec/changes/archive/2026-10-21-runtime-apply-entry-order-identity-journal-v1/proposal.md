## Why

The `entry_package_applied` record (`runtime-apply-entry-order-values-journal-v1`) has `trade_cycle_id` and the four order values, but nothing that links it to the Engine evaluation that led to the apply, or to the physical Bybit order. Without both, the Central Journal cannot connect plan and order without guessing.

## What Changes

- The record gains `bar_open_time_ms`: the committed bar whose processing sent the apply, the same bar and name as in `live_entry_evaluated`.
- Runtime accepts optional `order_link_id` and `order_id` in ABI's `entry_package_applied` response and copies them into the same record.
- No new state, no decision uses the values, no change to `schema_version`, the envelope or other events.

## Capabilities

### Modified Capabilities

- `abi-entry-package-client`: two more optional response fields.
- `processing-journal`: three more payload fields in `entry_package_applied`.

## Impact

`entry_package_models.py`, `entry_package_codec.py`, `entry_reconciliation/models.py`, `entry_reconciliation_bridge/bridge.py`, `entry_reconciliation_orchestrator` (port and call), `processing_journal/jsonl_adapter.py`, tests. Deploy before `abi-apply-entry-order-identity-v1`.
