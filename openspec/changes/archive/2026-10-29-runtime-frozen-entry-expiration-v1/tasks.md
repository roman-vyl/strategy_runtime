## 1. Config

- [x] 1.1 `RuntimeConfig.order_lifetime_bars: int | None`; validation per mode (required non-bool int >= 0 in `touch_trigger`; optional, validated if present, in `ema_anchor`)
- [x] 1.2 Loader accepts `order_lifetime_bars`; float, bool, string, negative → `ValueError` at start
- [x] 1.3 README and `config/runtime.toml.example`

## 2. Timeframe table

- [x] 2.1 New `strategy_runtime/runtime/timeframe.py` with the table and `timeframe_duration_ms`; `first_fill/alignment.py` uses it, behaviour unchanged

## 3. Decision and orchestrator

- [x] 3.1 `touch_trigger_entry_reconciliation` keyword inputs and expiry table (NoOp before expiry; Cancel on none or stale plan; Replace on fresh plan, also when equal)
- [x] 3.2 `EntryReconciliationOrchestrator(order_lifetime_bars=...)`, required in `touch_trigger`; passes processed bar open time and timeframe ms
- [x] 3.3 Bootstrap passes `config.order_lifetime_bars` to `EntryReconciliationOrchestrator` only

## 4. Tests (targeted only)

- [x] 4.1 Config: touch_trigger without key / 3.0 / -1 / true / "3" → error; 0 and 3 ok; ema_anchor without key ok, with key ok
- [x] 4.2 Decision: boundary bars for N = 0 and N = 3 (last NoOp bar, first expired bar), skipped bars, held plan's time used (new plans do not extend), Replace on equal plan, stale plan → Cancel, frozen-context and input-type errors
- [x] 4.3 Orchestrator: expiry Cancel and Replace go through the shared execution (marker, new trade_cycle_id), touch_trigger without lifetime → construction error, ema_anchor unchanged
- [x] 4.4 First-fill alignment tests unchanged and green; bootstrap passes the lifetime; ruff and mypy clean
