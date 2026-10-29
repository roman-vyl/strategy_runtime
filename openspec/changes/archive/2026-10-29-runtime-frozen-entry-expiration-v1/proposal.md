## Why

Owner plan 2026-10-28 11:44, step 2 technical decision 15:16, «пиши спек» 15:18 (thread «Перевести вход на цену
закрытия свечи касания»). After step 1 (`runtime-frozen-entry-reconciliation-v1`, PR #38) a `touch_trigger` entry is
held with no expiry. This change gives the held entry a lifetime counted in closed bars. After it, the `touch_trigger`
policy is functionally complete.

## What Changes

- Config: new key `order_lifetime_bars` in the Runtime config file (flat, next to `live_entry_mode`). In
  `touch_trigger` it is required and must be an integer `N >= 0`; missing, negative, fractional, boolean or non-number →
  Runtime refuses to start. In `ema_anchor` it is optional, validated if present, and unused. Read once at start.
- `touch_trigger_entry_reconciliation` gains keyword inputs `current_bar_open_time_ms`, `timeframe_ms`,
  `order_lifetime_bars` and decides:

  | state | Engine projection | decision |
  |---|---|---|
  | no cycle | none | NoOp |
  | no cycle | DesiredEntry | Apply |
  | held entry, not expired | any | NoOp |
  | held entry, expired | none | Cancel(trade_cycle_id) |
  | held entry, expired | DesiredEntry for the processed bar | Replace(trade_cycle_id, new) — also when equal to the held plan |
  | held entry, expired | DesiredEntry for another bar | Cancel(trade_cycle_id) |
  | position filled | any | existing Position Management routing (entry reconciliation is not called) |

- Expiry from the held (acknowledged) plan only:
  `expiration = held.source_plan_bar_open_time_ms + (N + 2) × timeframe_ms`;
  expired when `current_bar_open_time_ms + timeframe_ms >= expiration` (the processed bar's close reaches the
  boundary). The order is live N + 1 bars: N = 0 behaves like today's one-bar life. New signals do not extend it.
  A skipped bar is handled by the first processed bar past the boundary.
- `EntryReconciliationOrchestrator` receives `order_lifetime_bars` at construction (required in `touch_trigger`) and
  passes the processed bar's open time and the deployment timeframe in ms to the decision. Execution of Cancel/Replace,
  recovery, state and journals are unchanged.
- The timeframe → ms table moves from `first_fill/alignment.py` (private) to a small shared module used by both
  first-fill alignment and the orchestrator; first-fill behaviour unchanged.
- Bootstrap passes `config.order_lifetime_bars` to `EntryReconciliationOrchestrator` only.
- `decide_entry_reconciliation` (`ema_anchor`) unchanged. No new state fields, no timers, no extra ABI calls.

## Out of scope

- Integration scenarios (fill → Position Management, ABI timeouts, restart with a held order, fill right before
  cancel): step 3 `runtime-frozen-entry-integration-v1`.
- Engine, ABI (order type), Position Management, runtime state, recovery. bbb_stack and deployment.

## Impact

- `src/strategy_runtime/config/{model,loader}.py`, `runtime/entry_reconciliation/reconciliation.py`,
  `runtime/entry_reconciliation_orchestrator/orchestrator.py`, new shared timeframe module,
  `runtime/first_fill/alignment.py` (import only), `bootstrap/application.py`, README, `config/runtime.toml.example`,
  tests.
- Specs: `entry-reconciliation` (modifies the step-1 touch-trigger requirement), `entry-reconciliation-orchestrator`,
  `runtime-production-composition` (added requirements).
- Archive order: `runtime-live-entry-mode-config-v1`, then `runtime-frozen-entry-reconciliation-v1`, then this change.
