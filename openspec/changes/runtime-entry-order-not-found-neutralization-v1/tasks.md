## 1. Recovery client contract

- [x] 1.1 Add `entry_order_not_found` to the typed recovery response union with no
  applied package or fill facts.
- [x] 1.2 Extend the strict HTTP decoder and protocol tests for the valid fifth response,
  invalid conditional fields, and unknown response members.
- [x] 1.3 Document and test that Runtime never derives the fifth state from marker age,
  clean errors, `internal_error`, or `unknown_trade_cycle_binding`; ABI is the sole
  evidence/freshness authority.

## 2. Uncertain-APPLY neutralization

- [x] 2.1 In the locked uncertain-APPLY branch, send exactly one existing corrective
  CANCEL when recovery returns `entry_order_not_found`, preserving the pending exact
  strategy/cycle identity.
- [x] 2.2 Clear the marker only for exact matching formal `EntryPackageAbsent`; leave all
  state unchanged for errors, mismatches, unexpected applied results, or unknown results.
- [x] 2.3 Add tests proving the branch never sends CREATE, never reconstructs desired
  entry, and performs at most one bounded corrective call per attempt.

## 3. Regression boundaries

- [x] 3.1 Add tests proving uncertain removal retains its existing table and that
  `entry_order_not_found` in removal context changes nothing and sends no command.
- [x] 3.2 Confirm `PendingEntryRecovery` remains `trade_cycle_id`-only and no durable state
  migration, timestamp, action discriminator, or retry counter is added.
- [x] 3.3 Add a regression proving an aged-out ABI safe error leaves the marker untouched
  and sends no corrective command.
- [x] 3.4 Run the canonical Runtime test/lint/type checks and strict OpenSpec validation.
  Recovery-focused tests, lint, format, mypy, and strict OpenSpec validation pass. The
  full suite has four pre-existing sibling Change 7 position-management OpenAPI contract
  mismatches (`/close` and `shared_scope_protection_unsupported`); no recovery test fails.

## 4. Coordinated Phase A verification

- [ ] 4.1 Deploy Runtime before or atomically with paired ABI change
  `abi-entry-order-not-found-recovery-v1`, without editing the two incident markers.
- [ ] 4.2 For each incident still inside ABI's trustworthy evidence window, capture
  `entry_order_not_found → corrective CANCEL → EntryPackageAbsent → marker cleared`; if
  outside, confirm no fifth state and no state mutation.
- [ ] 4.3 Verify no old CREATE was resent and the next genuine bar resumes ordinary fresh
  reconciliation for each strategy instance.
