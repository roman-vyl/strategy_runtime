## Why

Runtime already receives a singular `desired_entry: DesiredEntry | null`, owns
minimal current-cycle state, and has an ABI entry-package client, but it lacks
an approved pure boundary for deciding reconciliation, building a command, and
applying a matching successful confirmation.

## What Changes

- Add exact complete value-equivalence for immutable `DesiredEntry` values.
- Add the closed payload-bearing decision variants `NoOp`, `Apply`,
  `Replace`, and `Cancel`, so each decision carries the desired entry and
  existing cycle identity it requires.
- Add pure construction of an I3-owned `EntryReconciliationCommand` from
  aggregate identity/spec data, one decision variant, and an optional
  caller-reserved cycle identity used only by `Apply`.
- Make absence of a command a successful result only for `NoOp`; incoherent
  `Apply`, `Replace`, or `Cancel` inputs raise the single fail-closed
  `EntryReconciliationInvariantError`.
- Add pure application of only I3 success confirmations for applied package or
  package absence, raising that same invariant error for a confirmation
  inconsistent with the expected action, ownership, sent desired entry, or
  source state.
- Keep public ABI errors, timeout, network failure, protocol failure, and
  missing successful results out of the I3 applier; I4 will not invoke the
  transition component when no successful confirmation exists.
- **BREAKING**: Make `CurrentTradeCycle.applied_entry_package` required.
  `current_trade_cycle = null` becomes the only representation of no
  Runtime-owned acknowledged trade cycle; an empty cycle is invalid and has no
  recovery or compatibility semantics.
- Specify exhaustive decision, command-error, success-transition,
  confirmation-invariant, decimal-preservation, and dependency-isolation
  tests.
- Keep the ABI call, repository, mutex, ID reservation, Engine flow,
  orchestration, error journaling, and production composition outside I3.

## Capabilities

### New Capabilities

- `entry-reconciliation`: Defines exact desired-entry comparison, pure
  reconciliation decisions, pure I3 command construction with explicit
  invariant failure, and pure application of successful confirmations using
  one shared domain exception and no failure-result model.

### Modified Capabilities

- `current-trade-cycle-state`: Simplifies `AppliedEntryPackage` to the
  acknowledged desired entry plus calculated quantity, makes the package
  mandatory whenever a cycle exists, and defines confirmed `Apply`,
  `Replace`, and `Cancel` transitions.

## Impact

- Future Runtime implementation changes `AppliedEntryPackage`,
  `CurrentTradeCycle.applied_entry_package` nullability, and their tests before
  adding the pure I3 decision, command, and success-transition components.
- The existing ABI request/response DTOs, HTTP codec, outbound port, OpenAPI
  conformance, and ABI Executor contract remain unchanged by I3.
- A future I4 adapter will translate between I3-owned pure commands and success
  confirmations and the existing ABI client at the actual call boundary.
- Public ABI error and transport/protocol behavior remains owned by the
  existing client and future I4 orchestration, not by the I3 state applier.
- This OpenSpec package itself changes no production or test code, external
  repository, Runtime orchestrator, handoff boundary, delivery-map status, or
  HTML documentation.
