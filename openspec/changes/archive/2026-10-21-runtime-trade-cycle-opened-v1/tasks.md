## 1. strategy_runtime

- [x] 1.1 Open-position codec and `OpenPositionLookupResponse` per D1/D2; resolver passes both identifiers into the resolved state.
- [x] 1.2 Recovery-state codec and `PositionOpenRecoveryState` per D1/D2.
- [x] 1.3 `TradeCycleOpenedJournalPort`, helper, `ProcessingJournalEventType.TRADE_CYCLE_OPENED`, JSONL adapter method per D4; production composition wires the adapter into the orchestrator and the resolver.
- [x] 1.4 Bar path per D3 A; recovery path per D3 C.
- [x] 1.5 Tests:
  - codecs: six-key bodies for open and closed shapes, `entry_order_id: null` accepted when open, every old body without the keys rejected, wrong per-state values rejected (null link id when open, non-null ids when closed, empty strings);
  - bar path: first freeze writes one record after the save with this bar's time; a second bar with the same open position writes none; `save` failure writes none;
  - recovery path: uncertain Apply resolved as `position_open` writes one record with `bar_open_time_ms: null`; uncertain removal with `position_open` writes none, the next bar writes it;
  - journal failure does not raise and does not change the saved state;
  - existing flows unchanged apart from the two added keys in fixtures.
- [x] 1.6 Targeted tests, `ruff`, `mypy`, `openspec validate --all --strict` green.

## 2. Rollout (on owner's word only)

- [x] 2.1 Runtime PR merges before the ABI PR; Runtime and ABI are deployed together.
- [ ] 2.2 On the Mac demo: the next real entry fill gives exactly one `trade_cycle_opened` record in `runtime.jsonl`.
