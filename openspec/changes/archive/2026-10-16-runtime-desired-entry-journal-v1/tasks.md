## 1. strategy_runtime

- [x] 1.1 Add `LIVE_ENTRY_EVALUATED = "live_entry_evaluated"` to `ProcessingJournalEventType`; bump journal envelope `schema_version` to 2.
- [x] 1.2 Add port method `live_entry_evaluated(*, strategy_instance_id, instrument, timeframe, bar_open_time_ms, desired_entry)`; implement in `JsonlProcessingJournal` with the D3 payload.
- [x] 1.3 Call it right after a successful `project_live_entry` and before entry reconciliation (D2); wire the port in `bootstrap/application.py`.
- [x] 1.4 Add `os.fsync` after `flush` in `_record`; keep failure absorption and `failure_count`.
- [x] 1.5 Tests: event written for non-null and for null `desired_entry`; written when the following ABI call fails; not written when Engine fails, on pending-recovery skip, or on the open-trade path; journal failure does not affect the bar outcome; exact payload and decimal text.

## 2. Verification on the Mac (on owner's word only)

- [x] 2.1 Confirm ABI runs dry-run or demo; handle the enabled `loadtest-*` specs as the owner decides.
  2026-10-16: ABI `3d46c76` `/health` `dryRun: true`, `liveTradingEnabled: false`, testnet, no API key. All 32 `loadtest-*` specs set to `enabled: false` (files kept).
- [x] 2.2 Enable one strategy, wait for three real 5m bars.
  2026-10-16: Runtime built locally from `15e7fed`; only `journal-smoke-eth-ema500` enabled (ETHUSDT.P 5m, EMA 200/500/1000, `touch_anchor`, no blockers). Bars 17:35, 17:40, 17:45 UTC delivered by MDS, no manual webhooks.
- [x] 2.3 `journal/runtime.jsonl` has three `live_entry_evaluated` lines for that `strategy_instance_id` with three consecutive `bar_open_time_ms`; `desired_entry` is `null` whenever Engine returned no entry, and equals the Engine response otherwise.
  2026-10-16: passed. Three `live_entry_evaluated` lines for `ema_pullback:3e2e0f79752a9ed6cfffa1ca`, `bar_open_time_ms` 1792172100000 / 1792172400000 / 1792172700000, `desired_entry: null` each (Engine returned no entry). Central Journal stored all three.
