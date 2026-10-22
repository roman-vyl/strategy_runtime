## Why

The Runtime Dashboard chart should show, for the selected strategy, the EMA lines of that strategy's own stack and later the EMA stack episodes (legs, half-waves). The front must not read the deployment specification itself and must not guess periods: defaults such as the stack of an episode are resolved by Strategy Engine's one parser. Runtime already holds every accepted specification and already talks to Strategy Engine, so it is the place that answers "which EMA stack and which episode parameters does this strategy use".

## What Changes

- New read-only route `GET /v1/strategy-instances/{strategy_instance_id}/chart-layers`.
- Runtime sends the instance's `raw_spec` to Strategy Engine's existing `POST /v1/strategies/{strategy_id}/feature-plan` and returns only what the chart needs, taken from the plan unchanged:
  - `ema_stack`: the anchor-stack EMAs as `{role, timeframe, period, source}`, resolved through the plan's own mapping `anchor_columns` (`fast`, `anchor`, `slow` → `output_id`) and the planned feature with that `output_id` (its `timeframe`, `source` and `parameters.period`);
  - `episodes`: per `episode_ref` the effective episode parameters (`episode_params_by_ref`), empty when the spec declares no `ema_stack_episode`.
- No parsing of `raw_spec` in Runtime, no second period or default resolver.
- No state change, no file change, no ABI call, no Journal event. Nothing is cached in V1 (the answer is cheap and a spec file can change).
- `GET /v1/strategy-instances` is unchanged.

## Capabilities

### New Capabilities

- `strategy-chart-layers`: the route, its answer, and its refusals.

## Impact

`adapters/http` (route and models), a small service in `runtime/` and a Strategy Engine feature-plan adapter in `infrastructure/strategy_engine`, production composition, tests, README. Strategy Engine, ABI, Journal, state schema, Research and docker compose are unchanged. The frontend change is separate (`research_frontend`, `runtime-dashboard-ema-episodes-v1`) and is deployed after this one.
