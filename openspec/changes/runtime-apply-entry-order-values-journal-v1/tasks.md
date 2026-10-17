## 1. strategy_runtime

- [ ] 1.1 Add the four optional fields to `EntryPackageApplied` and `EntryAppliedConfirmation`; accept them in `entry_package_codec.py` (exact-decimal, nullable stop-loss and take-profit); pass them through `bridge.py`.
- [ ] 1.2 Add `trade_cycle_id` to `ProcessingJournalEvent`, an `ENTRY_PACKAGE_APPLIED` event type, an optional port method and adapter implementation. `schema_version` is not changed.
- [ ] 1.3 Inject the optional port into `EntryReconciliationOrchestrator`; emit per D2; wire it in `bootstrap/application.py`.
- [ ] 1.4 Tests: old-shape responses decode unchanged; new shape decodes; unknown key and wrong types rejected; event content verbatim; no event when the fields are absent or on cancel, absent and error outcomes; journal failure does not change the outcome; durable state file and codec unchanged; `live_entry_evaluated` unchanged.

## 2. Verification on the Mac (on owner's word only)

- [ ] 2.1 Deploy this change before the ABI change. ABI on Bybit demo.
- [ ] 2.2 One apply on demo; `runtime.jsonl` has one `entry_package_applied` line with `strategy_instance_id`, `trade_cycle_id` and the four values matching the order in Bybit demo Orders.
