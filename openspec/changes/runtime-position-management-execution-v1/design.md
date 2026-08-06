## Context

`position-management-decision` (archived) already selects exactly one
`NoOp` / `ApplyProtection` / `ClosePosition` from a `PositionManagementRecipe`
and the current trade cycle's effective acknowledged protection, and nothing
calls that function outside its own tests. `entry-reconciliation-orchestrator`
(archived) already solved the analogous problem for entry: a pure decision,
an abstract `EntryReconciliationExecutionPort.execute(command, source_state)`,
a confirmation-gated `apply_success_confirmation` state transition, and an
`EntryReconciliationOrchestrator.execute(projection)` that composes all three
with no mutex and no repository ownership — those stay in the outer
`StrategyRuntimeOrchestrator` layer. This change is the direct position-
management analog of that boundary, produced one change ahead of any ABI-
backed implementation, exactly as the entry-reconciliation orchestrator
(2026-07-24) was built and archived before `abi-entry-package-client-v1`
(2026-07-26) and its production bridge (2026-07-29).

## Goals / Non-Goals

**Goals:** a Runtime-owned abstract execution port for `ApplyProtection` and
`ClosePosition`; typed commands carrying only what Runtime owns
(`strategy_instance_id`, `trade_cycle_id`, and — for protection — the desired
stop/take); typed confirmations; a pure, fail-closed function applying a
matching confirmation to `CurrentTradeCycle`; an orchestrator composing the
existing decision, one port call, and confirmed state replacement, mirroring
`EntryReconciliationOrchestrator`'s shape.

**Non-Goals:** any HTTP client, ABI wire codec, or Bybit call; close-quantity
or exchange-step computation; partial close; retries, timeouts, or pending-
command state; wiring this orchestrator into `StrategyRuntimeOrchestrator` or
production composition; any mutex or repository ownership inside this
boundary.

## Decisions

**Two named port methods, not one `execute(command)`.** Unlike
`EntryReconciliationExecutionPort` (one `execute` over a closed
`Apply | Replace | Cancel` command union), `PositionManagementExecutionPort`
exposes `apply_protection(command, source_state)` and
`close_position(command, source_state)` as two methods with two distinct
command and confirmation types. The two actions have no shared shape to
justify a union (one carries desired protection, the other carries none),
and a future ABI-backed implementation maps each directly onto a distinct
wire operation. Alternative considered: a single `execute` over a two-member
union, rejected because it would force either a runtime `isinstance` branch
inside every port implementation or an artificial shared command shape.

**Commands carry no ticker/instrument.** `EntryReconciliationCommand` carries
`ticker` because the ABI entry-package endpoint is instrument-scoped.
`ApplyProtectionCommand` / `ClosePositionCommand` carry only
`strategy_instance_id` and `trade_cycle_id` — the same pair `abi-open-
position-lookup-client` already uses to address a position, with no
independent instrument parameter. Any future ABI contract that needs the
instrument can derive it from that pair the same way position lookup does.

**`ClosePosition` has no quantity or `close_fraction` field.** Issuing
`ClosePositionCommand` means "close the entire current position." Runtime
owns no exchange-side remainder; the future executor is responsible for
reading the actual position size, closing it entirely with a reduce-only
order, and verifying zero. Adding a `close_fraction` field now would invent a
partial-close concept with no consumer and no decision path that could ever
produce a fractional value (`position-management-decision` only ever emits
whole-position `ClosePosition`). If partial close is ever needed, it is a new
decision variant and a new command shape, not a hidden field on this one.

**Confirmation application is a pure function, not a method on state.**
`apply_position_management_confirmation(state, decision, sent_command,
confirmation)` mirrors `apply_success_confirmation` exactly: it type-checks
every input, requires `strategy_instance_id` to match the source state on
both `sent_command` and `confirmation`, requires `trade_cycle_id` to match
across the decision, the current trade cycle, `sent_command`, and
`confirmation`, requires the confirmation variant to match the decision
variant (`ApplyProtection` → `ProtectionAppliedConfirmation`, `ClosePosition`
→ `PositionClosedConfirmation`), and — for `ApplyProtection` — requires
`confirmation.confirmed_protection` to equal both `decision.desired_protection`
and `sent_command.desired_protection`. Any mismatch raises
`PositionManagementExecutionInvariantError` and returns nothing; the caller's
state reference is never touched, matching the existing
copy-on-write/`dataclasses.replace` pattern used throughout `state_applier.py`
and `state/models.py`.

**The orchestrator owns no mutex or repository, matching the entry
precedent.** `PositionManagementOrchestrator.execute(projection:
OpenTradeProjectedStrategyInstance) -> StrategyInstanceRuntimeState` reads
`projection.source.resolved_state.runtime_state` as `source_state`, calls the
existing `decide_position_management(projection.position_management_recipe,
source_state.current_trade_cycle)`, returns `source_state` unchanged for
`NoOp`, otherwise builds the matching command from `source_state` and the
decision, calls exactly one port method, and applies the returned
confirmation through the pure state-transition function. Any exception raised
by the port propagates uncaught — the orchestrator returns a new state only
on a fully matched, successful confirmation, never a partial one. Keyed
coordination and repository persistence remain the responsibility of the
outer `StrategyRuntimeOrchestrator`, unchanged by this proposal.

**Module layout mirrors the entry pair.** `position_management_execution/`
holds the transport-free command, confirmation, and error types plus the pure
command-builder and confirmation-application functions (mirroring
`entry_reconciliation/`). `position_management_orchestrator/` holds
`PositionManagementExecutionPort` and `PositionManagementOrchestrator`
(mirroring `entry_reconciliation_orchestrator/`). No code is added to
`position_management_decision/`, which stays exactly what it is: the pure
decision boundary this change consumes unchanged.

## Risks / Trade-offs

- [No concrete port implementation exists yet, so the orchestrator is only
  exercised against fakes] → Accepted, matching the entry-reconciliation
  precedent; a future change adds the ABI-backed bridge the same way
  `runtime-production-outbound-adapters-v1` followed
  `entry-reconciliation-orchestrator-v1`.
- [A future ABI bridge could still violate the port's implicit "call exactly
  once, no retry" expectation] → Not enforceable at the `Protocol` level in
  this change; the future bridge's own spec (mirroring
  `entry-reconciliation-execution-bridge`) is expected to state and test this
  explicitly, as it already does for entry.
- [Omitting `close_fraction` now means a future partial-close feature is a
  breaking addition, not an additive one] → Accepted; inventing an unused
  field today would misrepresent what the current decision layer can ever
  produce.

## Open Questions

None — the two-method port shape, the no-ticker command shape, and the
full-close-only semantics are settled decisions for this change, not open
questions.
