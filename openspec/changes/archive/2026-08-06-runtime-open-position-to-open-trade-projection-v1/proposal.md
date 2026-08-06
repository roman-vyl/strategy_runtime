## Why

`position_open=true` currently stops before Strategy Engine with
`OpenTradeContextUnavailable`, even though the pieces needed to go further
already exist: an in-memory `CurrentTradeCycle`, the first-fill transition,
and a fully specified open-trade Engine adapter.

## What Changes

- Orchestrator applies the existing first-fill transition and saves the
  resulting changed state before routing, whenever a resolved position is
  open.
- Router builds the open-trade request from the registered spec snapshot
  and the frozen entry context, calls Strategy Engine, and returns the
  typed projection.
- The existing unsupported post-projection boundary is unchanged — this
  only makes it reachable.

## Capabilities

### Modified Capabilities

- `strategy-runtime-orchestrator`: applies the first-fill transition ahead
  of routing an open position.
- `use-case-router`: routes an open position from a frozen entry context
  instead of failing closed unconditionally.

## Non-Goals

Applying the Engine response (protection, close signal, diagnostics); ABI
position-management execution; cold-restart recovery or lost-trade-cycle
search; a persistent Runtime state repository; any change to the ABI or
Strategy Engine wire contracts.
