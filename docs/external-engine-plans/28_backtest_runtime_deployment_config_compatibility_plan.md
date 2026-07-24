# Plan 28 — Backtest compatibility with the Runtime deployment-config envelope

## Status

Deferred plan only. No Research Service, backtest module, or Strategy Engine code is changed by the Runtime decision.

## Runtime decision to accommodate

Runtime deployment JSON now contains strategy semantics plus required `ticker` and `base_timeframe`. It does not carry a manually assigned `strategy_instance_id`; Runtime derives that identity from the canonical semantic deployment payload.

## Required future analysis

1. Inventory every backtest/research input format that currently carries strategy semantics separately from ticker and timeframe.
2. Choose one compatibility boundary:
   - make backtest configs use the same complete deployment envelope; or
   - keep strategy-only research specs and add an explicit adapter that combines the spec with experiment market coordinates.
3. Ensure the combined backtest deployment identity uses the same canonical fields as Runtime when identity parity is required.
4. Do not expose Runtime's internal derivation hash as a cross-service correlation or validation field.
5. Add parity tests proving that the same strategy semantics, ticker, and timeframe resolve to the same deployment identity basis regardless of the originating workflow.
6. Preserve batch workflows that intentionally run one strategy semantic spec over many ticker/timeframe combinations; each combination must become a distinct deployment instance.

## Non-goals

- No immediate backtest migration.
- No Engine contract change in this plan.
- No reintroduction of `spec_revision_hash`, `source_config_hash`, or `market_data_hash` into Runtime information exchange.
