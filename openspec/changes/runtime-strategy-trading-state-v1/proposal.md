## Why

The Runtime Dashboard cards show only whether a strategy is enabled. The owner needs to see on each card whether the strategy is in a position now and, separately, whether it has a placed entry order waiting to fill. Runtime owns the trade-cycle lifecycle and already keeps exactly this in its durable state (`current_trade_cycle`: the applied entry package, and the frozen entry context once the entry filled), but no route exposes it. The strategy list deliberately excludes state (`strategy-instance-list`: "no item contains … trade-cycle, recovery-marker … field"), so the list keeps its contract and a separate read-only route answers.

## What Changes

- New read-only route `GET /v1/strategy-instance-states`. For every accepted deployment of the catalog, in catalog order, it returns one item read from the state repository:
  - `strategy_instance_id`;
  - `trade_state`: `flat` (no current trade cycle), `entry_pending` (a current cycle whose entry package is applied and whose fill Runtime has not recorded), or `in_position` (a current cycle with a frozen executed-entry context);
  - `trade_cycle_id` and `side` (`long` / `short`) of the current cycle, `null` when flat;
  - `first_fill_at_ms` of the current cycle, `null` unless in position;
  - `recovery_pending`: `entry`, `close` or `null`, from the pending recovery markers.
- An instance without stored state (never processed) is `flat` with `recovery_pending: null`.
- The answer is Runtime's own view as of its last processed bar. A fill or exit that happened on the exchange after that bar shows only after Runtime processes the next bar. The route does not query ABI or Bybit.
- Failures follow the list route: `503 not_ready`, `503 catalog_unavailable`, `503 state_unavailable` when the state store cannot be read, `500 internal_error`; never a partial answer.

## Non-goals

- No change to `GET /v1/strategy-instances`, to the state model, to the orchestrator, to ABI or to the Journal.
- No exchange query, no polling, no pending-order details beyond the side.

## Safety

Read-only: no state, journal, catalog, queue or mutex write. No trading behavior changes. Dry-run, demo and mainnet guards are untouched.

## Capabilities

### New Capabilities

- `strategy-instance-trading-state`: the read-only trade state of every deployed strategy instance.

## Impact

`src/strategy_runtime/adapters/http/app.py` and `models.py` (route and response models), a small read service over the deployment catalog and the state repository, OpenAPI, tests. Consumer: research_frontend (`runtime-dashboard-card-trading-state-v1`).
