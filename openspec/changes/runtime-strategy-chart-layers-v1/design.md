## Context

`GET /v1/strategy-instances` lists `strategy_instance_id`, `strategy_id`, `instrument`, `base_timeframe`, `enabled`, `source_path`. The raw specification stays inside Runtime. Strategy Engine's feature plan (`ema-pullback-feature-plan-v1`, `ema-stack-episode-v1`) already resolves the anchor stack and the effective episode parameters: for `ema_stack_episode: {trend: {}}` it returns `episode_params_by_ref.trend` with the defaults filled in (`fast_period`, `anchor_period`, `slow_period`, `window_bars`, `break_bars`, `history_bars`). The same parameters are what the history route `POST /v1/ema-stack-episodes/history` takes.

## Decisions

- **D1 Engine resolves, Runtime relays.** Runtime calls `POST /v1/strategies/{strategy_id}/feature-plan` with `{strategy_id, raw_spec}` of the accepted deployment and copies the needed fields. Runtime never reads `anchor_stack` or `ema_stack_episode` itself. Rejected: reading periods from `raw_spec` in Runtime (duplicates the parser and misses defaults); reading the spec in the browser.
- **D2 A separate route, not new fields on the list.** The list stays cheap and Engine-free; the chart asks for one strategy when it is selected. A list request must keep working while Strategy Engine is down.
- **D3 Role, timeframe and period come from the plan's own mapping.** The feature-plan wire already carries an unambiguous contract (`ema-pullback-feature-plan-v1`, "Deterministic feature discovery": the planner exposes stable lookup mappings keyed by role that resolve to the planned features' `output_id`s; implemented as `anchor_columns = {"fast", "anchor", "slow"} → output_id`, tests `test_ema_pullback_feature_plan.py` and `test_ema_pullback_feature_plan_api.py`). Runtime resolves each role in this fixed way and in no other:
  1. `output_id = plan["anchor_columns"][role]` for `fast`, `anchor`, `slow`;
  2. the one entry of `plan["features"]` with that `output_id` (`kind` `ema`) gives `timeframe` (the literal `"base"` for the strategy's base timeframe, or a concrete timeframe such as `"1h"`), `source`, and `parameters.period`;
  3. the answer entry is `{"role", "timeframe", "period", "source"}` with those values unchanged; `"base"` is NOT replaced by Runtime (the instance's `base_timeframe` is already in the list answer, and the frontend compares `"base"` or an equal concrete timeframe with the chart's).
  Runtime never uses the order of `features`. If a role is missing from `anchor_columns`, no feature has its `output_id`, the feature is not `kind` `ema`, or `parameters.period` is not a positive integer, the plan is not valid and the route answers `502 engine_unavailable` (D4). Answer shape: `{"strategy_instance_id", "ema_stack": [{"role","timeframe","period","source"} fast, anchor, slow], "episodes": [{"episode_ref", "params": {...}}]}`. `episodes` is in the order of `episode_params_by_ref`; `params` is Engine's object unchanged (the episode EMAs are always the base-timeframe stack, so no timeframe field is needed there).
- **D4 Same rules as other routes.** Unknown id or a duplicate or invalid file: `404` `strategy_instance_not_found`. Runtime not ready: `503` not-ready body. Catalog unreadable: `503` `catalog_unavailable`. Strategy Engine unreachable or timing out: `502` `engine_unavailable`. Engine rejects the spec: `422` `engine_rejected` with Engine's error code and message passed through. Any answer that is not a valid plan: `502` `engine_unavailable`. Failure bodies are `{"status":"chart_layers_refused","reason":<code>}`.
- **D5 Read only.** No mutex, no state read, no ABI call. It works for enabled and disabled strategies.
- **D6 Out of scope.** Caching, other timeframes of EMAs, ATR or RSI overlays, indicator values (the front takes values from Research), episode data itself (the front takes it from Research and Engine), any write.

## Risks

- A slow Engine slows only this route; the timeout is the existing Engine timeout setting.
- A strategy kind whose plan has no `anchor_columns` is refused as an invalid plan (`502`), not guessed; today the one strategy kind, `ema_pullback`, always has the stack.
