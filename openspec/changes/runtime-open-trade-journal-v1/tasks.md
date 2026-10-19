## 1. strategy_runtime

- [ ] 1.0 ABI position management codec and `ProtectionAppliedConfirmation` carry `protection_orders` per D6.
- [ ] 1.1 `ProcessingJournalEventType.OPEN_TRADE_EVALUATED` and `PROTECTION_APPLIED`; `JsonlProcessingJournal.open_trade_evaluated` and `.protection_applied` per D2/D4/D5.
- [ ] 1.2 `OpenTradeEvaluationJournalPort` and the orchestrator call per D1.
- [ ] 1.3 `ProtectionAppliedJournalPort` and the position management call per D3.
- [ ] 1.4 Production composition wires the JSONL journal into both ports.
- [ ] 1.5 Tests:
  - fidelity: record equals the decoded Engine answer field by field (fake Engine with trailing-zero prices, null take, every close-signal field set), no extra keys;
  - NoOp bar writes one `open_trade_evaluated` with `side`, protection and inactive close signal, and no `protection_applied`;
  - codec: six-key body with both legs accepted; old five-key body, missing/extra leg keys, empty `order_id`, bad decimals rejected; `take_price: null` with a `take` leg accepted;
  - ApplyProtection writes one `open_trade_evaluated` and one `protection_applied` with ABI's confirmed values, both orders' ids, trigger prices and quantities, and this bar's time, `protection_applied` before the save;
  - ClosePosition writes `open_trade_evaluated` with the active close signal and no `protection_applied`;
  - short position journals `side: "short"`; `take_price: null` journaled as JSON `null`;
  - no record on pending recovery skip, closure on resolve, entry bar after committed bar, Engine failure; no `protection_applied` on ABI failure while `open_trade_evaluated` stays;
  - journal failure does not raise and does not change state; no diagnostics in the payload;
  - existing flows unchanged.
- [ ] 1.6 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy`, `openspec validate --all --strict` green.

## 2. Rollout (on owner's word only)

- [ ] 2.1 PR, merge, deploy only on the owner's word; Runtime and the matching ABI change are deployed together.
- [ ] 2.2 On the Mac demo: an open position gives one `open_trade_evaluated` per bar in `runtime.jsonl`, and a protection change gives one `protection_applied` whose `stop_order.order_id` and `take_order.order_id` match the orders on Bybit.
