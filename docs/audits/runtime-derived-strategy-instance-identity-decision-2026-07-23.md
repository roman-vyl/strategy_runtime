# Runtime derived strategy-instance identity decision

## Decision

Runtime deployment JSON is a complete live deployment configuration. It MUST contain:

- `ticker`;
- `base_timeframe`;
- `strategy_id`;
- `raw_spec`.

It MUST NOT contain `strategy_instance_id`.

The utility deployment catalog derives `strategy_instance_id` deterministically from the canonical semantic deployment payload:

```text
strategy_id
+ ticker
+ base_timeframe
+ raw_spec
```

The source filename, JSON formatting, JSON key order, and non-semantic catalog metadata do not participate in identity.

## Consequences

- Any strategy-semantic change creates a new Runtime strategy instance.
- Any ticker or base-timeframe change creates a new Runtime strategy instance.
- Semantically identical deployment files resolve to one identity and fail closed as duplicate catalog declarations.
- Downstream Runtime modules continue to use `strategy_instance_id`; only the filesystem input ceases to supply it manually.
- A separate frozen-strategy ID or trade-cycle strategy snapshot identity is unnecessary: one derived strategy instance already binds immutable semantics to exact market coordinates.

## Deferred compatibility work

The backtest/research configuration path currently uses a strategy-only configuration format in places. It MUST later be adapted explicitly rather than weakening the Runtime deployment contract. That work should define whether backtest inputs adopt the same complete deployment envelope or are transformed into it by a boundary adapter.


## 2026-07-23 simplification

`strategy_version` and `compatibility_profile` were removed. `strategy_id` now selects the only supported strategy implementation and the schema/semantics of `raw_spec`. The derived identity basis is exactly `strategy_id + ticker + base_timeframe + raw_spec`.
