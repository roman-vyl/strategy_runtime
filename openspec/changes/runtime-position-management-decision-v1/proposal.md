## Why

Runtime already produces a `PositionManagementRecipe` for an open position
but has no way to turn it into one unambiguous execution decision.

## What Changes

- Add a pure decision boundary selecting exactly one of `NoOp`,
  `ApplyProtection`, or `ClosePosition` from a recipe and the current trade
  cycle.
- `close_signal.active = true` always wins over any protection change in
  the same recipe.
- Otherwise, desired protection is compared by exact value against the
  effective acknowledged protection: the latest confirmed management
  protection, else the initial protection from the frozen entry context.
- Extend `CurrentTradeCycle` with a nullable latest confirmed management
  protection field.

## Capabilities

- New — `position-management-decision`: selects one decision from a recipe
  and the trade cycle's acknowledged protection.
- Modified — `current-trade-cycle-state`: `CurrentTradeCycle` may hold a
  nullable latest confirmed management protection.

## Non-Goals

Applying a decision in `StrategyRuntimeOrchestrator`; an ABI client or
close/stop-take command; applying a confirmed result to Runtime state;
persistent Runtime state; any change to the Engine wire contract.
