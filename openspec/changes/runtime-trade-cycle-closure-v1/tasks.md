## 1. strategy_runtime

- [ ] 1.1 `TradeCycleClosure` per D1; open-position codec and `OpenPositionLookupResponse` per D2; resolver passes it through.
- [ ] 1.2 `apply_detected_trade_cycle_closure`; orchestrator step per D3.
- [ ] 1.3 Close codec and `PositionClosedConfirmation` per D4; journal after save on the bar path and in the resolver.
- [ ] 1.4 Journal port and adapter: `trade_cycle_closed` per D5.
- [ ] 1.5 Tests: old and new response shapes; invalid closure shapes; closure with `position_open: true` rejected; bar with closure saves no cycle, writes one record after the save, calls no Engine and no ABI apply; identity mismatch changes nothing; resolver clears `pending_close_recovery` on a `stop_loss` close confirmation and journals it with `bar_open_time_ms: null`; close with `closure: null` writes no record; existing flows unchanged.

## 2. Verification on the Mac (on owner's word only)

- [ ] 2.1 Deploy before the ABI change; nothing changes in `runtime.jsonl`. After ABI ships, one demo cycle exiting by stop or take-profit ends on the next bar with one `trade_cycle_closed` record.
