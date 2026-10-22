## ADDED Requirements

### Requirement: Runtime tells the chart which EMA stack and episode parameters a strategy uses
Runtime SHALL expose `GET /v1/strategy-instances/{strategy_instance_id}/chart-layers` with no body. A success answers `200` with `{"strategy_instance_id", "ema_stack", "episodes"}`. `ema_stack` SHALL list the three anchor-stack EMAs of the strategy as `{"role", "timeframe", "period"}` in the order fast, anchor, slow. `episodes` SHALL list, per `episode_ref` declared in the strategy's `ema_stack_episode`, `{"episode_ref", "params"}` where `params` is the effective parameter object resolved by Strategy Engine, unchanged. Runtime SHALL take both from Strategy Engine's feature plan of the instance's `raw_spec` and SHALL NOT read the periods from `raw_spec` itself.

#### Scenario: Strategy with a stack and an episode
- **WHEN** an accepted instance declares an anchor stack of 200, 500, 1000 and `ema_stack_episode: {trend: {}}`
- **THEN** Runtime answers `200` with `ema_stack` of three entries with periods 200, 500, 1000
- **AND** `episodes` holds `trend` with Engine's effective `fast_period`, `anchor_period`, `slow_period`, `window_bars`, `break_bars`, `history_bars`

#### Scenario: No episode section
- **WHEN** the specification declares no `ema_stack_episode`
- **THEN** Runtime answers `200` with `episodes: []` and the `ema_stack` as before

#### Scenario: Enabled and disabled alike
- **WHEN** the instance's `enabled` is true or false
- **THEN** Runtime answers the same

#### Scenario: Read only
- **WHEN** the route is called
- **THEN** Runtime changes no state, no file and no Journal, and makes no ABI call

### Requirement: The route refuses without guessing
Runtime SHALL answer a refusal with a body `{"status":"chart_layers_refused","reason":<code>}`: `404` `strategy_instance_not_found` for an id that is not an accepted deployment or belongs to a duplicate identity; `503` `catalog_unavailable` when the catalog cannot be scanned; `502` `engine_unavailable` when Strategy Engine cannot be reached, times out, or answers something that is not a valid plan; `422` `engine_rejected` when Strategy Engine rejects the specification, with Engine's error code and message in the body. When Runtime is not ready it SHALL answer `503` with the not-ready body.

#### Scenario: Unknown instance
- **WHEN** the id is not an accepted deployment
- **THEN** Runtime answers `404` with reason `strategy_instance_not_found` and makes no Engine call

#### Scenario: Engine down
- **WHEN** Strategy Engine is unreachable or times out
- **THEN** Runtime answers `502` with reason `engine_unavailable`

#### Scenario: Engine rejects the spec
- **WHEN** Strategy Engine answers a rejection of the specification
- **THEN** Runtime answers `422` with reason `engine_rejected` and Engine's code and message

#### Scenario: Not ready
- **WHEN** Runtime is not ready
- **THEN** Runtime answers `503` with the not-ready body and makes no Engine call

### Requirement: The strategy list does not depend on Strategy Engine
`GET /v1/strategy-instances` SHALL keep its fields and SHALL NOT call Strategy Engine.

#### Scenario: Engine down, list still works
- **WHEN** Strategy Engine is unreachable
- **THEN** the list request answers as before
