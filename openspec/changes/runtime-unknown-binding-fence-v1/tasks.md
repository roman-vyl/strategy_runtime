## 1. Resolver

- [ ] 1.1 Catch `AbiEntryCycleRecoveryUnknownTradeCycleBinding` before the generic client
  error; in the uncertain-APPLY branch call `_cancel_and_clear_only_if_exact_absent`.
- [ ] 1.2 Keep uncertain removal plus 422 unchanged (no CANCEL, no state change).

## 2. Tests

- [ ] 2.1 422 + exact `EntryPackageAbsent` → marker and cycle null, exactly one CANCEL with
  `desired_entry: null` and the marker's trade_cycle_id.
- [ ] 2.2 422 + CANCEL error / timeout / mismatched identity / non-absent result → state
  unchanged.
- [ ] 2.3 422 with `current_trade_cycle != null` → no CANCEL, state unchanged.
- [ ] 2.4 Other query errors (500, timeout, protocol) → no CANCEL, state unchanged.
- [ ] 2.5 Acceptance with the paired ABI change: delayed non-null PUT after the CANCEL
  creates no order.
- [ ] 2.6 `make verify` (targeted tests during development).

## 3. Deploy (only on owner's word)

- [ ] 3.1 Confirm the deployed ABI contains `abi-unknown-pair-recovery-tombstone-v1`.
