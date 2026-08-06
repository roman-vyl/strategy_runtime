## Context

`position-management-decision` (archived) selects `NoOp` / `ApplyProtection`
/ `ClosePosition`; nothing calls it outside its own tests.
`entry-reconciliation-orchestrator` (archived) already solved the analogous
problem for entry: decision → command → execution port → confirmation →
fail-closed state transition, composed by an orchestrator that owns no mutex
and no repository. This change is the position-management analog of that
sequencing.

## Goals / Non-Goals

**Goals:** an abstract execution port for `ApplyProtection` and
`ClosePosition`; commands and confirmations carrying only what Runtime owns;
confirmations that mean a verified terminal fact, not an accepted request; a
fail-closed state transition; an orchestrator composing decision, one port
call, and confirmed state replacement.

**Non-Goals:** any HTTP client, ABI wire codec, or Bybit call; close-quantity
or exchange-step computation; partial close; retries or pending-command
state; wiring into `StrategyRuntimeOrchestrator` or production composition;
any mutex or repository ownership inside this boundary; the external-close
(exchange-initiated) lifecycle.

## Decisions

**Mirror the entry-reconciliation *sequencing*, not its exact port
signature.** Decision → command → port → confirmation → state transition
stays identical to `EntryReconciliationOrchestrator`. But
`EntryReconciliationExecutionPort.execute(command, source_state)` passes the
whole aggregate to the executor because entry construction needs
`source_state.risk_multiplier`. Position-management commands already carry
every value an executor needs (`strategy_instance_id`, `trade_cycle_id`,
`desired_protection`), so `PositionManagementExecutionPort` takes only the
command. `source_state` stays inside the orchestrator and the state
transition — never passed to the port.

**Two named methods, `apply_protection`/`close_position`, not one
`execute(command)` union.** This keeps explicit command→confirmation typing
inside Runtime. It is not a claim about the future ABI wire contract — that
boundary is a separate, later design and may end up as one endpoint or two.

**Confirmations are terminal, verified facts.** `ProtectionAppliedConfirmation`
SHALL be returned only once the executor has verified the requested
protection is actually applied; `PositionClosedConfirmation` SHALL be
returned only once the executor has verified no open position remainder
exists. Neither confirmation carries exchange IDs or quantities — only the
semantic guarantee, matching how `EntryAppliedConfirmation` already
represents a verified applied package rather than a submitted request.

**`ClosePosition` has no quantity or `close_fraction` field.** The command
means "close the entire current position"; the future executor reads the
actual remainder and closes it. `position-management-decision` never
produces a fractional close, so no such field exists to carry one.

**The confirmed-close transition is scoped to Runtime-issued execution.**
`current_trade_cycle` clears via a matching `ClosePosition` confirmation in
this change; this does not define, and does not preclude, a future
external-close lifecycle (e.g. ABI reporting `position_open=false` after an
exchange-side stop/take/manual close).

**The orchestrator owns no mutex or repository**, matching
`EntryReconciliationOrchestrator`: keyed coordination and persistence stay
in the outer `StrategyRuntimeOrchestrator`.
