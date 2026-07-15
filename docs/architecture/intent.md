# Architectural Intent

## Context

The legacy BBB service combined market data, research orchestration, strategy calculation, live strategy orchestration, and exchange execution.

The new architecture separates these responsibilities into independent services. `strategy_runtime` is the live orchestration boundary.

## Agreed responsibility

Strategy Runtime coordinates active live strategy specs.

For every newly closed canonical bar relevant to an active spec, it:

1. receives a webhook from Market Data Service;
2. identifies active specs whose explicitly configured base stream matches that instrument and timeframe;
3. asks Strategy Engine to calculate each relevant spec against the latest canonical market-data state;
4. receives the calculation result;
5. forwards every successful current-point result for each permitted strategy instance to ABI Executor, including results that do not change the desired trading state.

## Explicit boundaries

Strategy Runtime does not:

- calculate EMA, RSI, setups, triggers, exits, or other strategy components;
- own or validate canonical candle history;
- audit or repair market-data continuity;
- run historical backtests;
- send orders directly to Bybit;
- own exchange balances, positions, orders, or exchange reconciliation.

Market Data Service owns canonical candles and stream readiness. A `ready` stream is the trusted data-integrity boundary. Strategy Runtime does not repeat Market Data Service continuity validation.

Strategy Engine owns strategy calculation and chooses the market data needed for the current-point calculation. Strategy Runtime does not provide a bounded range or triggering-bar identity to Strategy Engine. In v1, Runtime does not inspect the spec to discover additional stream dependencies: the supplied `ticker + timeframe` pair is the strategy's only Runtime-visible base stream.

ABI Executor owns exchange execution and reconciliation of each newly supplied strategy result against its currently known orders and positions. Runtime does not decide whether an unchanged result is a no-op, whether an existing pending order must be replaced, or whether protective orders must be updated.

## Backtest boundary

Backtest is an entirely separate execution path:

```text
Research Service
        |
        | spec + instrument + bounded window
        v
Strategy Engine
        |
        | backtest result
        v
Research Service
```

Backtest bypasses Strategy Runtime completely. It is mentioned here only to prevent live orchestration and bounded research execution from being mixed.
