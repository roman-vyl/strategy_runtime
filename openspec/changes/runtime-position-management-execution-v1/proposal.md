## Why

Runtime already selects exactly one `NoOp` / `ApplyProtection` / `ClosePosition`
decision from a `PositionManagementRecipe` (`position-management-decision`,
archived), but nothing turns `ApplyProtection` or `ClosePosition` into an
external action or folds a confirmed result back into `CurrentTradeCycle`. The
decision boundary is unreachable in production until this seam exists.

## What Changes

- Add `PositionManagementExecutionPort`, a Runtime-owned abstract execution
  boundary with two typed actions — `apply_protection(command, source_state)`
  and `close_position(command, source_state)` — each returning a typed
  confirmation or raising. No ABI HTTP implementation, Runtime HTTP client, or
  Bybit call ships in this change; only the abstract port and its Runtime-side
  contract.
- Add `ApplyProtectionCommand` (`strategy_instance_id`, `trade_cycle_id`,
  `desired_protection`) and `ClosePositionCommand` (`strategy_instance_id`,
  `trade_cycle_id`). `ClosePositionCommand` carries no quantity or
  `close_fraction` field — issuing the command means "close the entire
  position"; the executor determines the actual exchange remainder later.
- Add `ProtectionAppliedConfirmation` (`strategy_instance_id`,
  `trade_cycle_id`, `confirmed_protection`) and `PositionClosedConfirmation`
  (`strategy_instance_id`, `trade_cycle_id`).
- Add a pure, fail-closed confirmation-application function:
  - `ApplyProtection` + a matching `ProtectionAppliedConfirmation` replaces
    `CurrentTradeCycle.latest_confirmed_management_protection` with the
    confirmed value.
  - `ClosePosition` + a matching `PositionClosedConfirmation` sets
    `current_trade_cycle = None`.
  - Any mismatch in `strategy_instance_id`, `trade_cycle_id`, confirmation
    type, or (for `ApplyProtection`) confirmed protection value raises a
    typed invariant error and leaves the input state unmodified.
- Add `PositionManagementOrchestrator.execute(projection:
  OpenTradeProjectedStrategyInstance) -> StrategyInstanceRuntimeState`,
  composing the existing `decide_position_management`, command construction,
  exactly one execution-port call, and confirmation-gated state replacement —
  mirroring the existing `EntryReconciliationOrchestrator` shape. `NoOp`
  performs no port call and returns the source state unchanged.

## Capabilities

### New Capabilities
- `position-management-orchestrator`: the `PositionManagementExecutionPort`
  contract, its command/confirmation models, the fail-closed confirmation
  -application state transition, and the orchestrator that composes the
  existing decision with one port call and confirmed state replacement.

### Modified Capabilities
- `current-trade-cycle-state`: add the requirement that confirmed
  position-management execution — not only entry reconciliation — is the
  only way `latest_confirmed_management_protection` changes or
  `current_trade_cycle` clears via a close, and only after a matching
  confirmation.

## Impact

- New code under a new `runtime/position_management_execution/`-style module
  (exact layout decided in design.md); no change to `PositionManagementRecipe`,
  `position-management-decision`, the Strategy Engine wire contract, or
  `StrategyRuntimeOrchestrator`'s keyed critical section.
- Depends on the existing `position-management-decision` decision boundary,
  `current-trade-cycle-state` aggregate, and `OpenTradeProjectedStrategyInstance`
  routing model.
- Explicitly out of scope: the ABI HTTP endpoint and Runtime HTTP client for
  this capability, any Bybit call, close-quantity/step normalization, partial
  close, retries or recovery, pending-command state, the internals of ABI's
  executor, and any external-close (exchange-initiated close) lifecycle. Those
  are separate, later changes.

## Non-Goals

An HTTP-backed implementation of `PositionManagementExecutionPort`; wiring the
orchestrator into `StrategyRuntimeOrchestrator` or production composition;
mutex/repository ownership (unchanged, stays outside this boundary); any
change to how Strategy Engine's open-trade response is decided into a
`PositionManagementRecipe`.
