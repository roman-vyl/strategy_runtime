## Context

Step 1 (main f38452d): `EntryReconciliationOrchestrator` selects `touch_trigger_entry_reconciliation` in
`touch_trigger`; the function applies the first desired entry and then returns `NoOp`. The Engine is still called on
every closed bar, so its answer is available at expiry. The processed bar is `projection.source.processing_unit.committed_bar`
and the timeframe is `projection.source.processing_unit.deployment.base_timeframe`. Before reconciliation the Runtime
orchestrator asks ABI for the position; an open position moves the cycle to Position Management and reconciliation is not
called on that bar.

## Decisions

- **All expiry logic in the pure decision.** No timer, no new state, no new ABI call, no call-chain change. The
  orchestrator only passes data.
- **Signature.**
  `touch_trigger_entry_reconciliation(new_desired_entry, current_trade_cycle, *, current_bar_open_time_ms, timeframe_ms, order_lifetime_bars)`.
  Inputs validated: non-negative int bar time, positive int timeframe, non-negative int lifetime (bool rejected).
- **Expiry boundary.** `expiration = held.source_plan_bar_open_time_ms + (N + 2) × timeframe_ms`, expired when
  `current_bar_open_time_ms + timeframe_ms >= expiration`. Example N = 3, signal bar 12:00–12:05: Apply at 12:05, NoOp
  at 12:10/12:15/12:20, Cancel or Replace at 12:25 (close of bar 12:20–12:25). `held` is the acknowledged
  `applied_entry_package.applied_desired_entry`, never the new projection.
- **Replace at expiry is unconditional on equality.** A plan on the expiry bar is a new signal with a new lifetime: the
  old cycle ends, the new one gets a new `trade_cycle_id` (existing Replace = confirmed Cancel → Apply). Cost: ABI
  cancels and re-places the same order (measured 1–3 s each on demo).
- **Freshness guard.** Replace only when `new.source_plan_bar_open_time_ms == current_bar_open_time_ms`; otherwise
  Cancel. In `touch_trigger` the Engine always plans on the requested (processed) bar, so the guard should never fire; it
  prevents a stale plan from being placed.
- **Shared timeframe table.** `_SUPPORTED_TIMEFRAME_DURATIONS_MS` moves to `strategy_runtime/runtime/timeframe.py`
  with `timeframe_duration_ms(base_timeframe) -> int` (unsupported → `ValueError`). `first_fill/alignment.py` imports
  it; its behaviour and errors are unchanged.
- **Config.** `RuntimeConfig.order_lifetime_bars: int | None = None`. `__post_init__`: in `touch_trigger` it must be a
  non-bool int `>= 0`; in `ema_anchor` `None` or such an int. Loader accepts key `order_lifetime_bars`; a TOML float
  (`3.0`), bool, string or negative value is a start error. No default for `touch_trigger`.
- **Orchestrator.** New keyword `order_lifetime_bars: int | None = None`; construction fails in `touch_trigger` when it
  is `None` or invalid. In `ema_anchor` it is ignored. Bootstrap passes `config.order_lifetime_bars`.
- **Fill at the boundary.** Handled by existing routing (open position → Position Management). A fill between the
  position check and the Cancel is the same case as today's `ema_anchor` Cancel; ABI and existing recovery own it.

## Risks

- Engine and Runtime files can disagree; switch both together.
- Replace on an equal plan briefly leaves no order on the exchange (cancel + apply latency).
