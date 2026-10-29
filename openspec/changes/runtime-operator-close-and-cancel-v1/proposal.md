## Why

The owner needs two operator buttons for a strategy: leave the position now (with every related order cancelled and confirmed) and take off the resting entry order. Runtime already has every part: ABI's full close (neutralize entry, cancel stop and take, reduce-only market close, re-read verification, closure proof), Runtime's close path with the `pending_close_recovery` marker and the resolver that finishes it, the entry-order cancel step used by disable, and the per-instance mutex. What is missing is a way for a person to call them.

## What Changes

- Two Runtime HTTP commands, both operator overrides of the strategy's own decisions: they do not go through the per-bar route and Engine, and run under the same per-instance mutex as bar processing.
  - `POST /v1/strategy-instances/{id}/close-position`: leave the position.
  - `POST /v1/strategy-instances/{id}/cancel-entry-orders`: remove the resting entry order (the only order a strategy has before a fill).
- Both also set the strategy's `enabled` to `false`, so it cannot enter again on the next bar (owner decision 2026-10-29).
- Close: checks under the mutex, writes `enabled=false`, saves the `pending_close_recovery` marker before the ABI call, calls the existing `close_position` execution, applies the verified confirmation to the durable state, journals `trade_cycle_closed` with the closure ABI proved. If ABI gives no confirmation the marker stays and the existing resolver finishes the close.
- If ABI already shows the position open but the first fill is not yet frozen in Runtime's state, the command freezes it first by the same function and journal event the bar uses.
- Cancel: the existing disable cancel step (exact `absent` from ABI is the only success) followed by `enabled=false`; unlike a plain disable it runs even when the file already says disabled, so an order left behind by a file edit can still be removed.
- Failure answers: `404` unknown id, `409` with a reason, `502` ABI unavailable, `503` busy / not ready / catalog unavailable.

## Non-goals

No partial close, no change to ABI, Engine or the Journal schema, no new journal event (`trade_cycle_closed` and `entry_cycle_ended` already exist), no Close-by-signal change, no frontend (separate change in research_frontend), no re-enable button.

## Capabilities

### New Capabilities

- `strategy-operator-commands`: operator close-position and cancel-entry-orders commands.

## Impact

`adapters/http/{app.py,models.py}`, a new `runtime/operator_commands/` service reusing `EntryOrderCancelStep`, `PositionManagementExecutionPort`, the state applier, first-fill freeze and the journal ports, `bootstrap/application.py`, tests. Rollout on the owner's word only; Runtime restart.
