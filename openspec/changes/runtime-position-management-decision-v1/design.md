## Context

Runtime's open-trade router already produces a `PositionManagementRecipe`
(`desired_protection`, `close_signal`, `diagnostics`) and holds
`CurrentTradeCycle.frozen_entry_context`, whose `desired_entry` carries the
initial stop/take already applied through the entry package. Nothing yet
turns a recipe into an actionable decision.

## Goals / Non-Goals

**Goals:** a pure, deterministic function from one recipe and the current
trade cycle to exactly one decision; a minimal state extension recording
the last acknowledged management protection.

**Non-Goals:** invoking the decision from `StrategyRuntimeOrchestrator`; an
ABI position-management client; applying an execution result back into
Runtime state.

## Decisions

**Pure decision boundary.** Selection stays a value-in/value-out function
with no repository, port, or orchestrator dependency — mirroring the
existing entry-reconciliation boundary.

**Close priority is absolute.** `close_signal.active = true` selects
`ClosePosition` unconditionally; a simultaneous protection change in the
same recipe is discarded, not merged or queued.

**Effective acknowledged protection has exactly two sources, in order.**
The latest confirmed management protection, if Runtime has recorded one;
otherwise the initial protection implied by
`frozen_entry_context.desired_entry`'s stop/take.

**Comparison is exact value equality.** `DesiredProtection` is an existing
exact-decimal immutable value; equality (including `take_price` present on
one side and null on the other) needs no tolerance or float conversion.

**State gains exactly one nullable field, not a history.** The last
acknowledged management protection replaces in place, never appends to a
ledger, matching how `CurrentTradeCycle` already avoids phase or
execution-lifecycle state. `diagnostics` reaches neither the decision nor
state.

**Invariant failures are typed and fail closed.** A missing or unfrozen
current trade cycle, or a wrong-typed value, is a domain-invariant
violation — matching `FirstFillInvariantError` /
`EntryReconciliationInvariantError`.

**Execution and acknowledgement are later changes.** How a decision
reaches ABI, and how its confirmation updates state, are separate seams.
