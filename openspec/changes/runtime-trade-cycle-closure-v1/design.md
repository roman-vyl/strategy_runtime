## Context

Audit of main `cfe173a`: the only cycle-clearing transition for a filled cycle is `state_applier._close_position` (`current_trade_cycle=None, pending_close_recovery=None`). `pending_close_recovery` is saved before the close call; while it is set, bar processing returns before the lookup (`orchestrator.py:72`) and the background resolver repeats the close every 30 s (it survives restarts). ABI evidence: `abi-trade-cycle-closure-confirmation-v1`.

## Decisions

### D1. Closure value

`TradeCycleClosure(strategy_instance_id, trade_cycle_id, reason, order_id, order_link_id, parent_order_link_id)`, frozen, validated as ABI specifies: `reason` ∈ {`stop_loss`, `take_profit`, `runtime_signal`}; `order_id` non-empty; `order_link_id` non-null only for `runtime_signal`; `parent_order_link_id` non-null only for the protection reasons. It is never persisted.

### D2. Open-position client

Success keys: the three existing ones plus optional `closure` (`null` or the closed object). `closure` with `position_open: true` is a protocol error. During rollout a body without the key decodes as `closure = None`.

### D3. Bar path

In `StrategyRuntimeOrchestrator.process`, after `resolve` and before `_ensure_first_fill_frozen`/routing:

1. `closure is None` → unchanged flow. `position_open: false` with `closure: None` for a cycle with a frozen fill still raises in entry reconciliation (ABI never sends it; Runtime does not turn it into a close).
2. `closure` present → require `closure.strategy_instance_id == state.strategy_instance_id` and `closure.trade_cycle_id == current_trade_cycle.trade_cycle_id`, otherwise raise an invariant error and change nothing.
3. Apply `apply_detected_trade_cycle_closure(state, closure)`: a second entry next to `_close_position` returning `replace(state, current_trade_cycle=None, pending_close_recovery=None)`. It takes no decision or command, so "Runtime closed" and "Runtime found it closed" stay distinct while sharing one resulting state.
4. Save, then journal `trade_cycle_closed` with this bar's `bar_open_time_ms`, then return. No Engine call, no entry on this bar; the next bar starts with no cycle.

`pending_close_recovery` cannot be set here (early return), so this path never bypasses the recovery protocol.

### D4. Close path

The close client accepts optional `closure` in the `trade_cycle_closed` body; when present its identifiers must equal the command. `PositionClosedConfirmation` carries it. `_close_position` is unchanged.
- Bar path ClosePosition: the orchestrator saves the resulting state as today, then journals `trade_cycle_closed` when the confirmation has a closure (normally `runtime_signal`, `stop_loss`/`take_profit` when the exit beat the command).
- Resolver path: after `save`, journal `trade_cycle_closed` when the confirmation has a closure. There is no committed bar here, so `bar_open_time_ms` is `null`.
A confirmation with `closure: null` (never-filled cycle) clears state as today and writes no record.

### D5. Journal record

`trade_cycle_closed`, schema version 2, `strategy_instance_id` in the envelope, payload `{trade_cycle_id, bar_open_time_ms, reason, order_id, order_link_id, parent_order_link_id}` verbatim from ABI. Written only after the durable save succeeded; best effort like other records. `bar_open_time_ms` is the bar on which Runtime learned of the closure, not the exchange execution time.

## Risks

- Rollout order: Runtime first (accepts both shapes), then ABI.
- A record lost to a journal failure is not retried (same as existing events).
