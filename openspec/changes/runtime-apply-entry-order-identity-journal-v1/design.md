## Context

Facts from `main` (01d62ef):

- `StrategyRuntimeOrchestrator.process` journals `live_entry_evaluated` with `bar_open_time_ms = unit.committed_bar.open_time_ms` and then calls `EntryReconciliationOrchestrator.execute(projection)` in the same call.
- Inside `execute`, the same bar is `projection.source.processing_unit.committed_bar.open_time_ms`; the `entry_package_applied` record is written there.
- `source_plan_bar_open_time_ms` is the bar of the plan, not of the evaluation, and the same plan bar can appear in evaluations of many bars, so it is not a link key.

## Decisions

### D1. Evaluation bar in the record

The payload gets `bar_open_time_ms` from the projection. Link to the evaluation: (`strategy_instance_id`, `bar_open_time_ms`). If one bar is evaluated twice, two evaluations share that pair; they are told apart only by order, which this change does not resolve.

### D2. Order identity

`order_link_id` and `order_id` are optional non-empty strings in the response (absent or null means not reported), carried on the transient confirmation and copied verbatim into the payload, `null` when not reported.

### D3. When the record is written

The record is written when the applied response carries any of the four values or either identifier; otherwise, as now, nothing is written.
