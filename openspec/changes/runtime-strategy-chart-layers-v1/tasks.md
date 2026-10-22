## 1. strategy_runtime

- [ ] 1.1 Feature-plan adapter in `infrastructure/strategy_engine`: `POST /v1/strategies/{strategy_id}/feature-plan` with `{strategy_id, raw_spec}`, existing timeout; errors mapped to unreachable / rejected (with Engine's code and message) / invalid answer (D4).
- [ ] 1.2 `StrategyChartLayersService` in `runtime/`: finds the accepted deployment, calls the adapter, returns `ema_stack` by the role mapping of D3 (`anchor_columns` → planned feature, never the order) and `episodes` from `episode_params_by_ref`; no state, no ABI, no mutex (D5).
- [ ] 1.3 `GET /v1/strategy-instances/{id}/chart-layers` in the HTTP app with the codes and reasons of the spec; production composition wires it.
- [ ] 1.4 Tests: stack and episode answered from a plan; stack taken by mapping when the first three features are not the stack; `"base"` and a concrete timeframe copied unchanged; missing role, missing feature, non-EMA feature and bad period give `502`; defaults taken from Engine's `episode_params_by_ref`; no section gives `episodes: []`; enabled and disabled; unknown id makes no Engine call; duplicate or invalid file; not ready; catalog unavailable; Engine unreachable, timeout, rejection with code passed through, malformed answer; list route unchanged and works with Engine down; no state or file or Journal change.
- [ ] 1.5 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy src`, `openspec validate --all --strict` green; README updated.

## 2. Rollout (on owner's word only)

- [ ] 2.1 PR and merge only on the owner's word; deploy before the frontend change.
- [ ] 2.2 On the Mac demo: call the route for a running strategy and compare `ema_stack` and `episodes` with its specification file.
