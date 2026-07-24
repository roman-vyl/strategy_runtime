## Why

After state get-or-create and open-position resolution,
`StrategyRuntimeOrchestrator` holds one current processing item and the
authoritative ABI fact `position_open`. Runtime needs a narrow boundary that
selects one of the two Engine projections and returns typed, uninterpreted
projection data.

## What Changes

- add scalar `StrategyUseCaseRouter.route(item)`;
- validate the processing-unit, deployment, and runtime-state
  `strategy_instance_id` chain before any Engine request;
- route solely by `position_open`;
- map exact live-entry and open-trade Engine requests;
- require frozen entry context and execution facts for open-trade projection;
- validate all echoed strategy, instance, market, timeframe, and target-bar
  bindings;
- distinguish typed Engine transport unavailability from response-binding and
  missing-context failures;
- preserve open-trade diagnostics as an opaque recursively immutable mapping;
- return one typed projection to the same scalar orchestrator method;
- stop before state application, ABI commands, or exchange interpretation.

## Capabilities

### New Capabilities

- `use-case-router`: Routes one resolved strategy instance to one Engine
  projection and returns a typed result.
- `strategy-runtime-orchestrator`: Coordinates one processing unit through
  state get-or-create, position resolution, and Engine projection.

### Modified Capabilities

None.

## Impact

This change defines and implements the first semantic half of Runtime through
typed Engine projection. Production Engine HTTP adapters, repository writes,
ABI commands, recipe application, and trade-cycle transitions remain outside
the capability.
