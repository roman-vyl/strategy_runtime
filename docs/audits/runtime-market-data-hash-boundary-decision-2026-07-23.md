# Runtime market-data hash boundary decision — 2026-07-23

## Decision

`market_data_hash` is removed from Strategy Runtime information exchange.

Runtime does not:

- request it from Strategy Engine;
- accept it in Engine responses;
- persist it in `EntryRecipe` or `PositionManagementRecipe`;
- compare it between calls;
- forward it to ABI, journals, or runtime state.

The synchronous Runtime → Engine call is associated by the current object and call stack, not by provenance hashes. The exact committed target bar remains represented by `target_bar_open_time_ms`.

## Scope

This decision changes Runtime contracts, OpenSpec, documentation, and future DTO expectations only. Strategy Engine implementation is not modified here. Its cleanup is described in `docs/external-engine-plans/26_engine_market_data_hash_contract_cleanup_plan.md`.

## Non-goals

This decision does not define Research Service or offline backtest provenance. Those systems may make a separate decision if reproducible historical-window identity is required.
