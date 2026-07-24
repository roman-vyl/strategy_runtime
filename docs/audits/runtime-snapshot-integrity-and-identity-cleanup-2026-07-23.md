> **Superseded identity note (2026-07-23):** historical references to `strategy_version` and `compatibility_profile` describe the pre-simplification contract. Both fields are now removed from Runtime; see `runtime-strategy-selector-fields-removal-decision-2026-07-23.md`.

# Runtime snapshot integrity and identity cleanup — 2026-07-23

## Restored source

The canonical workspace was restored from:

`strategy-runtime-derived-instance-id-deployment-config-2026-07-23.zip`

The restored tree contains the complete Runtime source, tests, active OpenSpec changes, architecture documents, prior identifier/hash boundary decisions, and external Engine/backtest cleanup plans.

## Derived strategy-instance identity

Runtime deployment JSON contains the strategy contract coordinates, `ticker`, `base_timeframe`, and `raw_spec`. It MUST NOT contain `strategy_instance_id`.

The utility deployment catalog derives `strategy_instance_id` deterministically from:

- `strategy_id`
- `strategy_version`
- `compatibility_profile`
- `ticker`
- `base_timeframe`
- `raw_spec`

Source filename, JSON formatting, and JSON object-key order do not affect identity. Any semantic strategy, ticker, timeframe, contract-version, or compatibility-profile change creates a different instance identity.

## Confirmed previous simplifications

The current Runtime boundary decisions remain present and authoritative:

- former `flow_id` renamed to local-only `trace_id`, generated and discarded at HTTP ingress;
- `stable_deployment_id` removed in favor of canonical `strategy_instance_id`;
- Runtime-owned `trade_cycle_id` remains internal and is not mapped to Engine `trade_id`;
- strategy/config revision hashes removed from Runtime↔Engine information exchange;
- `market_data_hash` removed from Runtime information exchange;
- payload-level `contract_version` removed from Runtime information exchange.

A consistency pass also removed stale references to these superseded fields from
active Runtime OpenSpec changes. Removed cleanup candidates are not retained as
an active or archival contract in the working tree.

## Preserved external plans

The restored project contains:

- `24_trade_id_removal_plan.md`
- `25_engine_spec_hash_contract_cleanup_plan.md`
- `26_engine_market_data_hash_contract_cleanup_plan.md`
- `27_engine_contract_version_cleanup_plan.md`
- `28_backtest_runtime_deployment_config_compatibility_plan.md`

No Strategy Engine or backtest implementation code was modified by this Runtime pass.
