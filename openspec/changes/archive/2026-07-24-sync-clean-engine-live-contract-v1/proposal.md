## Why

Strategy Engine has removed Runtime-owned instance identity from live projection
requests and removed all request echoes from projection responses. Strategy
Runtime must consume that cleaned calculation-only contract without weakening
its own internal identity model.

## What Changes

- **BREAKING** Remove `instance_id` from Runtime's live-entry and open-trade
  Engine request DTOs.
- **BREAKING** Replace live-entry response echo fields and side-specific
  top-level fields with the Engine `plans_by_side` calculation result.
- **BREAKING** Remove all identity, market, timeframe, and target-bar echoes from
  both Engine response DTOs.
- Remove echo validation and `EngineResponseBindingError`.
- Bind each synchronous calculation result to the original
  `PositionResolvedStrategyInstance` held in local call context.
- Require strict response DTO construction to reject old echo-bearing payloads
  as unknown fields.
- Keep Runtime/ABI strategy-instance identity, routing, recipe models,
  open-trade receipt semantics, and HTTP payload nesting unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `use-case-router`: Align Engine request and calculation-result mapping with
  the cleaned live projection contract while preserving local Runtime identity.

## Impact

- Runtime Engine DTOs and ports under `runtime/engine/`.
- Scalar routing and projection mapping under `runtime/routing/`.
- Semantic pipeline fixtures and contract tests.
- Runtime System Plans and the main use-case-router specification.
- No change to repository, ABI, deployment identity, recipe, or lifecycle
  contracts.
