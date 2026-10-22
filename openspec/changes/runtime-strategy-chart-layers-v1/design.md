## Context

`GET /v1/strategy-instances` lists `strategy_instance_id`, `strategy_id`, `instrument`, `base_timeframe`, `enabled`, `source_path`. The raw specification stays inside Runtime. Strategy Engine's feature plan (`ema-pullback-feature-plan-v1`, `ema-stack-episode-v1`) already resolves the anchor stack and the effective episode parameters: for `ema_stack_episode: {trend: {}}` it returns `episode_params_by_ref.trend` with the defaults filled in (`fast_period`, `anchor_period`, `slow_period`, `window_bars`, `break_bars`, `history_bars`). The same parameters are what the history route `POST /v1/ema-stack-episodes/history` takes.

## Decisions

- **D1 Engine resolves, Runtime relays.** Runtime calls `POST /v1/strategies/{strategy_id}/feature-plan` with `{strategy_id, raw_spec}` of the accepted deployment and copies the needed fields. Runtime never reads `anchor_stack` or `ema_stack_episode` itself. Rejected: reading periods from `raw_spec` in Runtime (duplicates the parser and misses defaults); reading the spec in the browser.
- **D2 A separate route, not new fields on the list.** The list stays cheap and Engine-free; the chart asks for one strategy when it is selected. A list request must keep working while Strategy Engine is down.
- **D3 Answer shape.** `{"strategy_instance_id", "ema_stack": [{"role", "timeframe", "period"}], "episodes": [{"episode_ref", "params": {...}}]}`. `ema_stack` holds the three anchor-stack EMAs in the order fast, anchor, slow. `episodes` is in the order of `episode_params_by_ref`. `params` is Engine's object unchanged. The exact fields of the plan that carry the stack roles are read at apply time from `anchor_columns` and the planned features; if the plan does not state a role directly the first three planned features are the stack (a rule the plan spec already fixes).
- **D4 Same rules as other routes.** Unknown id or a duplicate or invalid file: `404` `strategy_instance_not_found`. Runtime not ready: `503` not-ready body. Catalog unreadable: `503` `catalog_unavailable`. Strategy Engine unreachable or timing out: `502` `engine_unavailable`. Engine rejects the spec: `422` `engine_rejected` with Engine's error code and message passed through. Any answer that is not a valid plan: `502` `engine_unavailable`. Failure bodies are `{"status":"chart_layers_refused","reason":<code>}`.
- **D5 Read only.** No mutex, no state read, no ABI call. It works for enabled and disabled strategies.
- **D6 Out of scope.** Caching, other timeframes of EMAs, ATR or RSI overlays, indicator values (the front takes values from Research), episode data itself (the front takes it from Research and Engine), any write.

## Risks

- A slow Engine slows only this route; the timeout is the existing Engine timeout setting.
- A future spec kind without an anchor stack gives `ema_stack: []`; the chart then shows nothing for it.
