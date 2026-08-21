## Why

Runtime currently treats an ambiguous APPLY whose exact ABI-owned order is cleanly absent
the same as an unavailable recovery query, so `pending_entry_recovery` can block all
future genuine bars forever. The paired ABI change exposes that narrow observation and
lets Runtime neutralize the old identity without ever resurrecting the stale CREATE.

## What Changes

- Decode the paired ABI recovery state `entry_order_not_found` as a fifth strict success
  member with no applied package or fill facts. Runtime SHALL trust only ABI's typed
  outcome; ABI alone owns ambiguous-CREATE structural eligibility, full bounded
  order/execution evidence, and the documented-retention freshness gate.
- For an uncertain APPLY only (`pending_entry_recovery != null` and
  `current_trade_cycle == null`), respond to that observation with exactly one bounded
  corrective CANCEL using the existing `abi_entry_cycle_recovery.cancel(...)` operation
  and the same `trade_cycle_id`.
- Clear `pending_entry_recovery` only when that CANCEL returns a formal
  `EntryPackageAbsent` whose strategy/cycle identity exactly matches the pending marker.
- Leave the marker and all Runtime state unchanged for any error, mismatch, unexpected
  result, or other response; a later poll retries from fresh ABI evidence.
- Preserve the existing uncertain-removal table unchanged. In particular,
  `entry_order_live` remains its only corrective-CANCEL trigger.
- Preserve the current minimal `PendingEntryRecovery { trade_cycle_id }` durable shape;
  add no desired entry, timestamp, action discriminator, or retry counter.
- Add no Runtime wall-clock check or aged-out inference. If ABI preserves
  `internal_error` outside its trustworthy evidence window, Runtime leaves the marker
  untouched.
- Never resend the old CREATE. After formal absence clears the marker, only a later
  genuine bar may calculate a fresh ordinary entry.
- Coordinate with ABI change `abi-entry-order-not-found-recovery-v1`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `abi-entry-cycle-recovery-client`: decode the fifth response member and preserve its
  strict null-field contract.
- `uncertain-exchange-state-resolver`: add the uncertain-APPLY neutralization row while
  leaving uncertain-removal behavior unchanged.

## Impact

- Affects the ABI recovery response domain type/decoder and the existing uncertain-state
  resolver's APPLY branch.
- Reuses the existing entry-package CANCEL port and HTTP write contract; no new endpoint,
  state schema, persistence migration, or Engine/Runtime routing dependency is added.
- Does not change ordinary bar reconciliation, CREATE construction, position management,
  first-fill handling, or deployment safety configuration.
