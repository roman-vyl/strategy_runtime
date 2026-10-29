## Context

- `touch_trigger_entry_reconciliation` (runtime-frozen-entry-expiration-v1): `expiration_ms =
  source_plan_bar_open_time_ms + (order_lifetime_bars + 2) × timeframe_ms`; the held entry ends on the bar where
  `current_bar_open_time_ms + timeframe_ms >= expiration_ms`. Example, 5m, signal bar 12:00, N = 3: Apply on the
  12:00 bar's processing, NoOp for 12:05, 12:10, 12:15, end on the 12:20 bar (closes 12:25).
- After a fill the orchestrator freezes the entry (`_ensure_first_fill_frozen` → `apply_first_fill`) and routes to
  position management; entry reconciliation is fail-closed for frozen cycles.
- `live_entry_mode` and `order_lifetime_bars` come from `RuntimeConfig`, passed from bootstrap.

## Decisions

### D1. The boundary is frozen at the first fill, from the original signal

`apply_first_fill(state, trade_cycle_id, first_fill_at_ms, *, order_lifetime_bars: int | None = None)`: when
`order_lifetime_bars` is an int (touch_trigger) it sets `entry_order_expires_at_bar` with the shared function from
the cycle's applied `DesiredEntry.source_plan_bar_open_time_ms` and the registered base timeframe; when `None`
(ema_anchor) it sets `null`. The value is never recomputed: a changed config or a restart does not move it, and a
partial or later fill does not extend it. A first fill observed after the boundary still freezes; the step then runs
on that same bar.

### D2. The mark lives on the cycle, not in the recipe

`CurrentTradeCycle.entry_remainder_cancelled: bool`, default false. It becomes true only through the step's
confirmed answer and is never reset for that cycle. It means "ABI confirmed no live remainder"; it is not a
quantity, phase or exchange identifier.

### D3. Where the step runs

Inside `StrategyRuntimeOrchestrator.process`, under the instance mutex, on the open-position path: after the
first-fill freeze and the existing entry-bar guard, before routing. Ordering: cancel first, then the normal open-trade
evaluation and position management on the updated state. A close decided on the same bar still neutralizes the entry
in ABI as today.

### D4. Failure never blocks position management

Every failure of the call (unavailable / timeout, documented ABI rejection, protocol failure) is caught by the step,
journaled `entry_remainder_cancel_failed` with the error class, and the bar continues with the unchanged state. The
next bar retries. A rejection like `entry_not_filled` or `unknown_trade_cycle_binding` is a contradiction, but the
narrow, idempotent cancel is safe to retry and position management must not stop for it.

### D5. Durable schema v4

New writes encode `schema_version = 4`: `current_trade_cycle.entry_remainder_cancelled` (bool, required) and
`frozen_entry_context.entry_order_expires_at_bar` (int or null, required key). Versions 1–3 decode with `false` /
`null`; no rewrite of old lines. Exact key sets stay enforced per version.

### D6. Journal

Two events on the processing journal: `entry_remainder_cancelled {strategy_instance_id, trade_cycle_id,
bar_open_time_ms, status, executed_quantity}` and `entry_remainder_cancel_failed {strategy_instance_id,
trade_cycle_id, bar_open_time_ms, error}`.

## Risks

- Exchange behaviour of SL/TP children on remainder cancel is ABI's acceptance item (Demo).
- A failing ABI repeats one call per bar until it recovers; bounded by the existing request timeout, no extra load
  pattern.
