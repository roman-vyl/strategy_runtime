# Runtime Engine-Projection Half-Pipeline Implementation Review — 2026-07-23

## Implemented boundary

The semantic Runtime path now starts at one utility `StrategyBarProcessingUnit` and ends at one typed live-entry or open-trade projection result.

```text
StrategyBarProcessingUnit
→ state repository get-or-create
→ ABI open-position lookup
→ route by position_open
→ Strategy Engine request
→ validate Engine response binding
→ typed projection result
```

## Deliberate stopping point

The implementation does not apply the returned recipe to durable state, create/freeze/close a trade cycle, derive execution commands, or call ABI execution endpoints. Those responsibilities form the next pipeline half and require separate OpenSpec review together with the ABI Executor Bot model.

## Review findings

- Utility and semantic boundaries remain separated.
- Runtime sends ABI only `strategy_instance_id` during position lookup.
- Routing depends only on ABI `position_open`.
- Live-entry and open-trade requests contain no hashes, profile/version selectors, flow/trace IDs, or trade IDs.
- Open-trade fails closed without a frozen entry recipe and exact execution facts.
- Engine response echoes are validated but not duplicated into recipes.
- Exact decimal text is normalized through `Decimal`, never binary float.
- Engine calculations remain uninterpreted and unpersisted at this seam.

## Deferred production adapters

The current implementation defines domain ports and transport models. Production HTTP adapters for ABI and Strategy Engine, and physical SQLite state persistence, remain placeholders because their final public contracts and lifecycle mutation semantics are still under review.
