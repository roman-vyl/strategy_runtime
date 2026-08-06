## 1. Commands, Confirmations, and Errors

- [ ] 1.1 Add `ApplyProtectionCommand` (`strategy_instance_id`,
  `trade_cycle_id`, `desired_protection`) and `ClosePositionCommand`
  (`strategy_instance_id`, `trade_cycle_id`), each rejecting empty identity
  fields and wrong-typed payloads.
- [ ] 1.2 Add `ProtectionAppliedConfirmation` (`strategy_instance_id`,
  `trade_cycle_id`, `confirmed_protection`) and `PositionClosedConfirmation`
  (`strategy_instance_id`, `trade_cycle_id`), with the same validation.
- [ ] 1.3 Add `PositionManagementExecutionInvariantError`, mirroring
  `EntryReconciliationInvariantError` / `PositionManagementDecisionInvariantError`.

## 2. Execution Port Contract

- [ ] 2.1 Define `PositionManagementExecutionPort` as a `Protocol` with
  `apply_protection(command, source_state) -> ProtectionAppliedConfirmation`
  and `close_position(command, source_state) -> PositionClosedConfirmation`.
  No implementation of this port ships in this change.

## 3. Confirmation-Application State Transition

- [ ] 3.1 Implement a pure `apply_position_management_confirmation(state,
  decision, sent_command, confirmation)` function analogous to
  `apply_success_confirmation`.
- [ ] 3.2 `ApplyProtection` + matching `ProtectionAppliedConfirmation`
  replaces `current_trade_cycle.latest_confirmed_management_protection` with
  the confirmed value; every other field of the cycle is preserved.
- [ ] 3.3 `ClosePosition` + matching `PositionClosedConfirmation` sets
  `current_trade_cycle` to null; every other field of
  `StrategyInstanceRuntimeState` is preserved.
- [ ] 3.4 Fail closed — raise `PositionManagementExecutionInvariantError` and
  return no new state — on: wrong confirmation variant for the decision,
  `strategy_instance_id` mismatch (command or confirmation) against
  `source_state`, missing or trade-cycle-id-mismatched
  `current_trade_cycle`, or (for `ApplyProtection`) a `confirmed_protection`
  that differs from the decision's or the sent command's
  `desired_protection`.

## 4. Command Construction and Orchestrator

- [ ] 4.1 Implement a pure command builder that turns an `ApplyProtection` or
  `ClosePosition` decision plus `source_state` into the matching command
  (`strategy_instance_id` sourced from `source_state`); return no command for
  `NoOp`.
- [ ] 4.2 Implement `PositionManagementOrchestrator.execute(projection:
  OpenTradeProjectedStrategyInstance) -> StrategyInstanceRuntimeState`:
  extract `source_state`, call the existing `decide_position_management`,
  return `source_state` unchanged for `NoOp`, otherwise build the command,
  call exactly the matching port method, and apply the returned confirmation
  through the state-transition function.
- [ ] 4.3 Let any exception raised by the port propagate uncaught; the
  orchestrator never returns a partially applied state.
- [ ] 4.4 Confirm the orchestrator acquires no mutex, performs no repository
  load/save, and performs no retry.

## 5. Verification

- [ ] 5.1 Unit tests for command/confirmation construction and validation
  (empty identities, wrong types).
- [ ] 5.2 Unit tests for the confirmation-application state transition:
  matching apply, matching close, every fail-closed mismatch scenario from
  `specs/position-management-orchestrator/spec.md`, and the
  state-unmodified-on-failure invariant.
- [ ] 5.3 Unit tests for `PositionManagementOrchestrator.execute` against a
  fake `PositionManagementExecutionPort`: `NoOp` calls neither method,
  `ApplyProtection` calls only `apply_protection` exactly once,
  `ClosePosition` calls only `close_position` exactly once, and a port
  exception propagates with no returned state.
- [ ] 5.4 Full test suite, `ruff check`, `ruff format --check`, `mypy`,
  `openspec validate` for this change and `--all`, both `--strict`.
- [ ] 5.5 Sync affected specs and archive this change after approval.
