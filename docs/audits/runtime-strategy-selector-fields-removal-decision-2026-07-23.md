# Runtime strategy selector fields removal decision

Date: 2026-07-23

## Decision

Remove `strategy_version` and `compatibility_profile` from Runtime deployment JSON, catalog models, derived identity, Runtime state inputs, and Runtime-to-Engine contracts.

`strategy_id` now has one unambiguous responsibility: it selects the only supported strategy implementation and therefore the schema and semantics of `raw_spec`. Runtime does not support multiple implementation versions or compatibility interpreters under one `strategy_id`.

## Canonical deployment JSON

```json
{
  "enabled": true,
  "ticker": "BTCUSDT.P",
  "base_timeframe": "5m",
  "strategy_id": "ema_pullback",
  "raw_spec": {}
}
```

## Derived identity

`strategy_instance_id` is derived from exactly:

- `strategy_id`;
- `ticker`;
- `base_timeframe`;
- `raw_spec`.

`enabled`, source path, JSON formatting, key order, and unknown non-semantic catalog metadata do not affect identity.

## Fail-closed migration rule

Deployment files containing `strategy_version`, `compatibility_profile`, or manual `strategy_instance_id` are rejected with `forbidden_obsolete_field`. This prevents stale configuration from being silently accepted.

## Engine boundary

Runtime no longer sends or expects either field. Engine implementation cleanup is specified in external plan 29 and is not performed in this repository.
