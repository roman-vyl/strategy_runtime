## Why

Owner plan 2026-10-29 (thread «Перевести вход на цену закрытия свечи касания», decisions 05:23 and 06:42). In
`touch_trigger` a partially filled GTC Limit entry moves the cycle to position management while the unfilled
remainder stays live on the exchange. The remainder must live exactly as long as the original order would have:
`order_lifetime_bars` counted from the original signal, with the existing Runtime formula and boundary. A partial fill
never extends it. After the boundary Runtime asks ABI to cancel the remainder and keeps managing the open position
as usual; on a failure it asks again on the next bar; after ABI confirms it never asks again.

Runtime knows the trade cycle and the expiry; ABI knows which exchange order belongs to the cycle
(`abi-entry-remainder-cancel-v1`). Runtime stores no exchange identifiers.

## What Changes

- **Frozen Entry Recipe** (`FrozenExecutedEntryContext`) gains `entry_order_expires_at_bar: int | null` — the
  immutable boundary, set once by `apply_first_fill`. In `touch_trigger` it is
  `desired_entry.source_plan_bar_open_time_ms + (order_lifetime_bars + 2) × timeframe_ms`, the same value
  `touch_trigger_entry_reconciliation` uses as its expiry; in `ema_anchor` it is `null`.
- **Open trade state** (`CurrentTradeCycle`) gains `entry_remainder_cancelled: bool` (false until ABI confirms), next
  to `latest_confirmed_management_protection`. The recipe stays immutable; the mark is execution state.
- **Per-bar step** in `StrategyRuntimeOrchestrator`, open-position path, after the first-fill freeze and before
  position management: when `entry_order_expires_at_bar` is non-null, the mark is false, and the bar is at or past
  the boundary (same comparison as entry reconciliation: `bar_open_time_ms + timeframe_ms >= entry_order_expires_at_bar`),
  Runtime calls ABI `POST .../entry-remainder/cancel`. Either confirmed answer (`entry_remainder_cancelled`,
  `entry_order_already_terminal`) saves the mark `true` and journals `entry_remainder_cancelled`. Any failure journals
  `entry_remainder_cancel_failed`, leaves the mark false (retry next bar) and does not stop the bar: position
  management runs as usual.
- The expiry boundary computation moves to one shared pure function used by both entry reconciliation and
  `apply_first_fill`.
- ABI client: `cancel_entry_remainder(strategy_instance_id, trade_cycle_id)` on the position-management HTTP client
  (same transport, timeout, error classes); strict response codec.
- Durable state: `schema_version = 4` carries both new keys; versions 1–3 decode with `null` / `false`.

## Unchanged

`ema_anchor` behaviour (boundary null, step never runs), entry reconciliation decisions, position-management
decisions, close, recovery markers, Runtime ↔ Engine contract, entry-package contract. No timers, no new routing,
no return to Entry Reconciliation after a fill, no exchange identifiers in Runtime state.

## Impact

- Capabilities: `first-fill-transition`, `current-trade-cycle-state`, `runtime-durable-state-store` (modified);
  `entry-remainder-cancel` (new).
- Depends on ABI `abi-entry-remainder-cancel-v1` deployed first. Builds on `runtime-frozen-entry-expiration-v1`
  (`order_lifetime_bars`, expiry formula), not yet archived.
