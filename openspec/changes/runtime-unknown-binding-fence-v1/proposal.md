## Why

`pending_entry_recovery` can stay forever when ABI never received the entry-package PUT
(lost in transit, Runtime timed out before ABI read it, ABI down, process killed before
its first durable write). ABI then answers every recovery-state query with
`422 unknown_trade_cycle_binding`, and Runtime correctly refuses to read that as
absence. Observed: BTC instance `6072511f…`, cycle `1e6fb986`, blocked 2026-10-19 → 10-21
(2936 identical 422 answers, released manually on 2026-10-21).

ABI change `abi-entry-admission-durable-outcome-v1` closes every PUT that ABI did receive.
This change closes the remaining case without any inference from 422: Runtime obtains
ABI's own durable proof of absence by fencing the pair.

## What Changes

- For an uncertain APPLY only (`pending_entry_recovery != null`,
  `current_trade_cycle == null`), when the recovery-state query fails with
  `unknown_trade_cycle_binding`, the resolver sends exactly one bounded corrective CANCEL
  (`desired_entry: null`) for the same `strategy_instance_id` and
  `pending_entry_recovery.trade_cycle_id`, through the existing
  `abi_entry_cycle_recovery.cancel(...)` operation.
- The marker is cleared only when that CANCEL returns formal `EntryPackageAbsent` whose
  strategy instance and trade-cycle identity exactly match the marker — the same
  acceptance rule as the existing `entry_order_not_found` row.
- Any other CANCEL outcome (error, timeout, mismatch, unexpected type) leaves all state
  unchanged; the next tick starts again from a fresh recovery-state query.
- The 422 itself is never evidence: it only selects the corrective action. The proof is
  ABI's durable fence written under its pair lock (paired ABI change
  `abi-unknown-pair-recovery-tombstone-v1`), which also refuses any later non-null PUT
  for that pair, so a delayed original PUT can never create an order after the release.

## Non-goals

- No TTL, attempt counter, marker age, or wall-clock check.
- No change to the uncertain-removal table (`current_trade_cycle != null`): a 422 there
  still changes nothing.
- No new durable Runtime fields; `PendingEntryRecovery { trade_cycle_id }` unchanged.
- No resend of the original CREATE; only a later genuine bar may compute a new entry.
- No change to the ABI recovery-state contract or the entry-package CANCEL contract.

## Deployment order

ABI `abi-unknown-pair-recovery-tombstone-v1` MUST be deployed before this Runtime change.
Against an ABI without the fence, a CANCEL on an unknown pair already returns
`entry_package_absent`, but a delayed non-null PUT could still create an order.

## Capabilities

### Modified Capabilities

- `uncertain-exchange-state-resolver`: uncertain APPLY plus `unknown_trade_cycle_binding`
  becomes the third corrective-CANCEL row.

## Impact

`runtime/uncertain_exchange_state_resolver/resolver.py` (APPLY branch of `attempt`),
focused resolver tests. No Engine, bar-path, state-schema or composition change.
