## 1. Commands, Confirmations, and Port

- [ ] 1.1 Add `ApplyProtectionCommand` / `ClosePositionCommand` and
  `ProtectionAppliedConfirmation` / `PositionClosedConfirmation` with their
  minimal fields and validation; add
  `PositionManagementExecutionInvariantError`.
- [ ] 1.2 Define `PositionManagementExecutionPort` (`apply_protection`,
  `close_position`), each taking only its command and documenting the
  terminal-confirmation contract (verified applied protection / verified
  zero remainder, not request acceptance). No implementation ships here.

## 2. Confirmation-Application State Transition

- [ ] 2.1 Implement a pure confirmation-application function for
  `current-trade-cycle-state`: matching `ApplyProtection` confirmation
  updates `latest_confirmed_management_protection`; matching `ClosePosition`
  confirmation clears `current_trade_cycle`.
- [ ] 2.2 Fail closed — raise `PositionManagementExecutionInvariantError`,
  return no new state — on any decision/command/confirmation identity,
  action-type, or protection-value mismatch.

## 3. Orchestrator

- [ ] 3.1 Implement a pure command builder from a decision and
  `source_state` (no command for `NoOp`).
- [ ] 3.2 Implement `PositionManagementOrchestrator.execute(projection)`:
  decide, return unchanged state for `NoOp`, otherwise call exactly the
  matching port method once and apply its confirmation via the state
  transition; let port exceptions propagate uncaught.
- [ ] 3.3 Confirm the orchestrator acquires no mutex, does no
  repository I/O, and retries nothing.

## 4. Verification

- [ ] 4.1 Unit tests for command/confirmation construction and validation.
- [ ] 4.2 Unit tests for the confirmation-application transition: matching
  apply, matching close, and each fail-closed mismatch.
- [ ] 4.3 Unit tests for the orchestrator against a fake port: `NoOp`,
  `ApplyProtection`, `ClosePosition`, and a propagated port failure.
- [ ] 4.4 Full test suite, `ruff check`, `ruff format --check`, `mypy`,
  `openspec validate --all --strict`; sync specs and archive after approval.
