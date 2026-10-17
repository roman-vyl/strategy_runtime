## 1. strategy_runtime

- [x] 1.1 Add the four optional fields to `EntryPackageApplied` and `EntryAppliedConfirmation`; accept them in `entry_package_codec.py` (exact-decimal, nullable stop-loss and take-profit); pass them through `bridge.py`.
- [x] 1.2 Add `ENTRY_PACKAGE_APPLIED` to `ProcessingJournalEventType` and one adapter method on `JsonlProcessingJournal` that calls the existing `_record` with the D2 payload. No change to `ProcessingJournalEvent`, `_record` or `schema_version`.
- [x] 1.3 Add the consumer-owned Protocol to `entry_reconciliation_orchestrator/ports.py`; pass it as an optional constructor argument to `EntryReconciliationOrchestrator`; call it per D2; wire the existing `journal` in `bootstrap/application.py`.
- [x] 1.4 Tests: old-shape responses decode unchanged; new shape decodes; unknown key and wrong types rejected; event content verbatim; no event when the fields are absent or on cancel, absent and error outcomes; journal failure does not change the outcome; durable state file and codec unchanged; `live_entry_evaluated` unchanged.

## 2. Verification on the Mac (on owner's word only)

- [ ] 2.1 Deploy this change before the ABI change. ABI on Bybit demo.
- [ ] 2.2 One apply on demo; `runtime.jsonl` has one `entry_package_applied` line with `strategy_instance_id`, `trade_cycle_id` and the four values matching the order in Bybit demo Orders.
