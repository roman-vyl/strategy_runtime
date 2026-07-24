## Context

The implemented semantic pipeline for one processing unit is:

```text
StrategyRuntimeOrchestrator.process(unit)
→ state_repository.get_or_create(request)
→ open_position_resolver.resolve(state)
→ use_case_router.route(PositionResolvedStrategyInstance(unit, resolved))
→ LiveEntryProjectedStrategyInstance
  | OpenTradeProjectedStrategyInstance
```

The projection is returned synchronously. This boundary does not apply it to
repository state or translate it into ABI commands.

## Goals / Non-Goals

**Goals:**

- Define scalar router and orchestrator boundaries.
- Validate strategy-instance identity before Engine calls.
- Route only by the ABI-resolved open-position fact.
- Map exact live-entry and open-trade projection requests.
- Validate Engine response echoes.
- Preserve Engine calculation objects without interpretation.
- Classify Engine transport unavailability at the adapter contract.
- Keep diagnostics opaque and recursively immutable.

**Non-Goals:**

- No Engine HTTP adapter implementation.
- No repository mutation or state-application capability.
- No entry execution, protection reconciliation, or close command.
- No recipe freezing or trade-cycle transition.
- No callback, exchange, or lifecycle interpretation.

## Decisions

### Use scalar orchestration

```python
class StrategyUseCaseRouterPort(Protocol):
    def route(
        self,
        item: PositionResolvedStrategyInstance,
    ) -> StrategyUseCaseProjectedInstance:
        ...
```

`StrategyRuntimeOrchestrator.process(...)` calls repository, resolver, and router
exactly once for its single processing unit. Fan-out and ordering are owned by
the utility orchestration layer, so the semantic router has no batch,
cardinality, or partial-result contract.

### Validate the strategy-instance binding chain first

Before constructing either Engine request, the router requires:

```text
processing_unit.strategy_instance_id
= processing_unit.deployment.strategy_instance_id
= resolved_state.runtime_state.strategy_instance_id
```

Any mismatch raises `StrategyInstanceBindingError` before an Engine port is
called. The router intentionally does not compare `raw_spec`, ticker, or
timeframe field by field: the utility-derived identity already binds
`strategy_id`, ticker, base timeframe, and the complete `raw_spec`.

### Route only by current ABI position state

```text
position_open = false → live-entry projection
position_open = true  → open-trade projection
```

Recipe presence is not a live-entry routing key.

### Map the live-entry projection

The request contains:

```text
strategy_id             <- deployment.strategy_id
instance_id             <- processing_unit.strategy_instance_id
raw_spec                <- deployment.raw_spec
ticker                  <- deployment.instrument
base_timeframe          <- deployment.base_timeframe
target_bar_open_time_ms <- committed_bar.open_time_ms
```

The router validates the response echo for every listed binding except
`raw_spec`, which is not echoed. A valid response becomes an `EntryRecipe`
containing the returned long and short plans, including null plans. The router
does not apply or freeze a trade-cycle recipe.

### Require exact open-trade context

For `position_open = true`, the router requires:

- a current trade cycle;
- `entry_recipe_frozen = true`;
- the cycle's immutable entry recipe;
- resolver-supplied entry bar open time;
- resolver-supplied executed entry price.

Missing context raises `OpenTradeContextUnavailable` before the Engine call.
The open-trade request uses the same strategy, instance, market, and target-bar
mapping as live entry, plus the frozen entry recipe and execution facts.
`trade_cycle_id` and exchange identifiers remain internal.

### Return uninterpreted management projection

A valid open-trade response becomes:

```text
PositionManagementRecipe
- desired_protection
- close_signal
- diagnostics
```

`diagnostics` is an opaque `Mapping[str, FrozenJsonValue]`. Runtime does not
define a required diagnostic field list. `PositionManagementRecipe` detaches
and recursively freezes arbitrary JSON-compatible nested values.

The router does not decide whether to replace protection, close a position, or
advance a phase.

### Keep failures typed and distinct

- Engine network, timeout, HTTP, and transport failures are classified by the
  Engine adapter as `StrategyEngineProjectionUnavailable`.
- A processing-unit identity-chain mismatch is
  `StrategyInstanceBindingError`.
- Missing frozen open-trade context is `OpenTradeContextUnavailable`.
- Any mismatch in the five Engine response echo fields is
  `EngineResponseBindingError`.

The router propagates typed adapter failures and has no blanket exception
handler, so programming defects are not relabeled as transport failures. No
empty or neutral recipe is fabricated.

The production Engine HTTP adapters are outside this change; port fakes verify
the error contract until those adapters exist.

### Stop at typed projection

The result is exactly one of:

```text
LiveEntryProjectedStrategyInstance
OpenTradeProjectedStrategyInstance
```

Each result retains its complete source item. `process(...)` returns it without
repository mutation or ABI execution. `dispatch(...)` adapts successful
semantic completion to the existing utility handoff outcome.

## Dependency Rules

The router may depend on processing-unit, runtime-state, resolver-view, recipe,
and Engine port models. It must not depend on repository adapters, ABI or
exchange implementations, state-application services, order builders, or
FastAPI handlers.

## Risks / Trade-offs

- [The projection is not repository state] → The stopping point is explicit and a
  later state-application capability must own lifecycle transitions.
- [Adapter classification is not exercised against production HTTP] → Typed
  port-fake tests define the contract until Engine adapters are implemented.
- [Diagnostics have no Runtime schema] → Recursive JSON validation and freezing
  preserve safety without coupling Runtime to Engine diagnostic evolution.

## Migration Plan

No persisted schema migration is involved.

## Open Questions

None.
