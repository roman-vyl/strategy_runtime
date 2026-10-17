## 1. strategy_runtime

- [ ] 1.1 Add `CycleExecutionState` / `EntryOrderObservation` frozen models with exact-decimal validation.
- [ ] 1.2 Extend `entry_package_codec.py`, `entry_cycle_recovery_codec.py`, `open_position_codec.py` to accept the optional fields (closed-field inner decode); attach to `EntryAppliedConfirmation`, `EntryOrderLiveRecoveryState`, `PositionOpenRecoveryState`, `OpenPositionLookupResponse`.
- [ ] 1.3 Add `trade_cycle_id` to `ProcessingJournalEvent`, `CYCLE_EXECUTION_STATE_OBSERVED` event type, journal port method and adapter implementation; `schema_version` 3.
- [ ] 1.4 Inject the optional journal port into the entry-reconciliation orchestrator, the resolver and the open-position resolution path; emit per D4; wire in `bootstrap/application.py`.
- [ ] 1.5 Tests: old-shape responses decode unchanged; each new shape decodes; unknown inner key and wrong types rejected; event content verbatim for applied, recovery and open-position; no event for cancel/absent/terminal/error; journal failure does not change outcomes; durable state file and codec unchanged; existing `live_entry_evaluated` events unchanged.

## 2. Verification on the Mac (on owner's word only)

- [ ] 2.1 Deploy this change before the ABI change. ABI on Bybit demo.
- [ ] 2.2 One strategy, three real 5m bars with an entry change; `runtime.jsonl` has `cycle_execution_state_observed` lines with `trade_cycle_id`; the `order_id` matches Bybit demo Orders.
