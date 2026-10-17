## 1. strategy_runtime

- [ ] 1.1 Optional `order_link_id`, `order_id` on `EntryPackageApplied` and `EntryAppliedConfirmation`; codec accepts them per D2; bridge passes them.
- [ ] 1.2 Journal port and adapter: `entry_package_applied` payload adds `bar_open_time_ms`, `order_link_id`, `order_id`; orchestrator passes the projection's bar per D1 and writes per D3.
- [ ] 1.3 Tests: old and new response shapes; empty or non-string id rejected; payload content verbatim with the evaluation bar equal to the `live_entry_evaluated` bar of the same `process` call; no record without values or ids, or on cancel, absent and error; state unchanged; `live_entry_evaluated` unchanged.

## 2. Verification on the Mac (on owner's word only)

- [ ] 2.1 Deploy before the ABI change. One apply on demo; the `runtime.jsonl` record has the bar of the preceding `live_entry_evaluated` and the order ids from Bybit demo Orders.
