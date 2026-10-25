## Why

ABI is getting a second sizing mode, `risk`, that sizes the entry from the wallet balance, the risk percent and the stop distance (ABI change `abi-entry-package-declined-and-risk-sizing-v1`). In that mode ABI can know, before it sends anything to Bybit, that an entry is impossible: the quantity rounded down to `qtyStep` is below the exchange minimum ("not enough money"), above the exchange maximum, the stop distance is zero or on the wrong side, or the account is in Isolated margin.

Today Runtime has no answer for "ABI refused, nothing was sent". Every non-success answer of `PUT …/entry-package` (`400`, `415`, `422`, `500`) becomes `EntryReconciliationExecutionError`, the `pending_entry_recovery` marker stays, bars of that strategy are skipped until the resolver clears it, and a `422` from request validation can leave the marker forever (`unknown_trade_cycle_binding`). An expected refusal must not look like a failure.

The owner decided (2026-10-25): a new explicit answer `entry_package_declined` with a reason, Runtime finishes the entry attempt without a trade cycle and without recovery, and Runtime is deployed first.

## What Changes

- The ABI entry-package client accepts a third success DTO: HTTP `200`, `status: "entry_package_declined"`, `decline_reason`, `decline_message`. It is valid only as the answer to a request with a non-null `desired_entry` (APPLY). The same answer to a CANCEL is a protocol error.
- The execution bridge maps it to a new transport-free value `EntryDeclinedOutcome` (`strategy_instance_id`, `trade_cycle_id`, `decline_reason`, `decline_message`).
- The entry-reconciliation orchestrator, on `EntryDeclinedOutcome` for an APPLY: creates no trade cycle, durably saves the state with `pending_entry_recovery = null`, journals `entry_package_declined`, and returns. The next bars run normally; if the strategy still wants the entry, the next bar sends a new APPLY with a new `trade_cycle_id`.
- The processing journal gets one event type, `entry_package_declined` (severity `warning`), with `trade_cycle_id`, `bar_open_time_ms`, `risk_multiplier`, `decline_reason`, `decline_message` exactly as received.
- Every other ABI answer keeps its current behavior: applied, absent, all public errors, timeouts, network and protocol failures, recovery and the resolver are unchanged.

No change to trading decisions, the request body, `risk_multiplier` (still sent as today), Runtime durable state shape, the recovery endpoint client, or the resolver.

## Capabilities

### Modified Capabilities

- `abi-entry-package-client`: third success DTO `entry_package_declined`, decoded strictly, APPLY only.
- `entry-reconciliation-execution-bridge`: maps the declined DTO to `EntryDeclinedOutcome`.
- `entry-reconciliation-orchestrator`: a declined APPLY ends the attempt without a cycle and without a recovery marker.
- `processing-journal`: new `entry_package_declined` event.

## Impact

`runtime/abi/entry_package_models.py`, `runtime/abi/entry_package_codec.py`, `runtime/entry_reconciliation/models.py` (new `EntryDeclinedOutcome`), `runtime/entry_reconciliation_bridge/bridge.py`, `runtime/entry_reconciliation_orchestrator/{orchestrator.py,ports.py}`, `utility/processing_journal/{models.py,jsonl_adapter.py}`, `bootstrap/application.py` (wire the journal port), contract tests and unit tests. No change to the ABI recovery client or the resolver.

Rollout order: this change first. While ABI does not send `entry_package_declined` the new path is never taken, so Runtime behaves exactly as today. ABI starts sending it only after its own change is deployed.
