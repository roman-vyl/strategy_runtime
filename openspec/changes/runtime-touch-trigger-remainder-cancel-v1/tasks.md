## 1. Code

- [x] 1.1 Shared pure `entry_order_expiration_ms(source_plan_bar_open_time_ms, timeframe_ms, order_lifetime_bars)` and `is_entry_order_expired(...)`; `touch_trigger_entry_reconciliation` uses them (behaviour unchanged)
- [x] 1.2 `FrozenExecutedEntryContext.entry_order_expires_at_bar: int | None`; `CurrentTradeCycle.entry_remainder_cancelled: bool = False`
- [x] 1.3 `apply_first_fill(..., order_lifetime_bars=None)`; orchestrator passes it from `RuntimeConfig` in touch_trigger only (also the ABI first-fill event, operator commands and uncertain-state resolver, which freeze fills too)
- [x] 1.4 Codec `schema_version = 4` with both keys; v1–v3 decode `null` / `false`
- [x] 1.5 ABI client `cancel_entry_remainder` + strict response codec on the position-management HTTP client
- [x] 1.6 Orchestrator step (D3/D4) + journal events (D6); production composition wiring

## 2. Tests (targeted only)

- [x] 2.1 First fill in touch_trigger sets the boundary from the signal bar (5m, N=3, signal 12:00 → boundary = 12:25); ema_anchor → null; late or partial fills do not move it; restart keeps it
- [x] 2.2 Step: before boundary no call; on the boundary bar one call; confirmed answers set the mark and journal; mark true → no further call
- [x] 2.3 Failure (timeout, 422, 500, protocol) → journal failed, mark false, position management still runs; next bar retries
- [x] 2.4 ema_anchor: step never calls ABI; entry reconciliation tests unchanged
- [x] 2.5 Codec: v4 round trip; v1–v3 lines decode; missing new key in v4 fails closed
- [x] 2.6 Client: exact route and body `{}`, response codec, error classes
