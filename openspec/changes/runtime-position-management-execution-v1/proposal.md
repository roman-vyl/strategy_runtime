## Why

Runtime already selects exactly one `NoOp` / `ApplyProtection` /
`ClosePosition` decision from a `PositionManagementRecipe`
(`position-management-decision`, archived), but nothing executes that
decision or folds a confirmed result back into `CurrentTradeCycle`.

## What Changes

- Add `PositionManagementExecutionPort`: two Runtime-owned actions,
  `apply_protection(command)` and `close_position(command)`, each taking
  only its own command and returning a typed confirmation. No ABI HTTP
  implementation ships in this change.
- Add `ApplyProtectionCommand` / `ClosePositionCommand` and
  `ProtectionAppliedConfirmation` / `PositionClosedConfirmation` — minimal
  identity plus payload, no exchange or transport detail.
- A confirmation is a terminal, verified fact, not an acceptance
  acknowledgement: `ProtectionAppliedConfirmation` means the executor
  verified the requested protection is actually applied;
  `PositionClosedConfirmation` means the executor verified no open position
  remainder exists. A command-accepted response alone is not a confirmation.
- Add a fail-closed confirmation-application state transition:
  `ApplyProtection` + a matching confirmation updates
  `latest_confirmed_management_protection`; `ClosePosition` + a matching
  confirmation clears `current_trade_cycle`. Any mismatch raises a typed
  invariant error and leaves state unchanged.
- Add `PositionManagementOrchestrator.execute(projection)`, composing the
  existing decision, one port call, and confirmed state replacement —
  mirroring `EntryReconciliationOrchestrator`, owning no mutex or
  repository.

## Capabilities

### New Capabilities
- `position-management-orchestrator`: the execution port, its commands and
  confirmations, and the orchestrator that composes decision, port call,
  and confirmed state replacement.

### Modified Capabilities
- `current-trade-cycle-state`: add the confirmed-execution rules for
  changing `latest_confirmed_management_protection` and clearing
  `current_trade_cycle`.

## Non-Goals

An HTTP/ABI implementation of the port; wiring into
`StrategyRuntimeOrchestrator` or production composition; close-quantity or
exchange-step handling, partial close, retries, or pending-command state;
any external-close (exchange-initiated) lifecycle — this change governs
only Runtime-issued `ClosePosition` confirmations.
