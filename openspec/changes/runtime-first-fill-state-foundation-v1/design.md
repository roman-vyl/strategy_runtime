## Context

Runtime's live-entry pipeline currently stops at `I4b`: entry reconciliation
creates and replaces `CurrentTradeCycle.applied_entry_package`, but nothing
in Runtime ever reacts to an actual fill. `docs/system-plans/
runtime-abi-entry-reconciliation-master-plan.md` §19-21 sketches the full
`I5` webhook path (`AbiExecutionEventOrchestrator`, fill aggregates,
`phase`, average price, partial/full fill state machine) as one large
future increment. That increment mixes two different kinds of work:

1. A pure domain operation — "the first fill freezes the entry context" —
   that has no dependency on HTTP, ABI wire shapes, the keyed mutex, or the
   repository.
2. Transport/orchestration wiring — HTTP handler, mutex acquisition,
   repository load/save, response mapping — that has no domain logic of its
   own once (1) exists.

This change builds only (1), as a self-contained, unit-testable foundation,
so that `I5` (`runtime-abi-first-fill-orchestration-v1`) reduces to wiring
an existing pure function into the existing orchestration pattern already
used by `EntryReconciliationOrchestrator`
(`runtime/entry_reconciliation_orchestrator/`).

`CurrentTradeCycle`, `AppliedEntryPackage`, `RegisteredSpecSnapshot`, and
`StrategyInstanceRuntimeState` already live in
`runtime/state/models.py` (`runtime-entry-state-foundation-v1`, archived
`I2`). `DesiredEntry` lives in `runtime/recipes/entry.py`. The pure
reconciliation transition (`apply_success_confirmation`) that this change's
`apply_first_fill` is modeled after lives in
`runtime/entry_reconciliation/state_applier.py`, with its own
`EntryReconciliationInvariantError` in
`runtime/entry_reconciliation/errors.py`.

## Goals / Non-Goals

**Goals:**
- Extend `CurrentTradeCycle` with exactly one new nullable field,
  `frozen_entry_context`.
- Define `FrozenExecutedEntryContext` with exactly `desired_entry`,
  `first_fill_at_ms`, `entry_bar_open_time_ms`.
- Provide `align_first_fill_to_entry_bar` as a small, pure, independently
  testable helper.
- Provide `apply_first_fill` as a small, pure, independently testable state
  transition with explicit idempotent-retry and fail-closed-conflict rules.
- Leave every other Runtime module (`repository`, `orchestrator`, `router`,
  `open_position`, `entry_reconciliation*`, ABI/Engine clients, HTTP) byte-
  for-byte unchanged.

**Non-Goals:**
- No `phase` field or any execution-phase state machine
  (`awaiting_entry` → `partially_filled` → `position_open`).
- No filled/remaining quantity, no average execution price, no fill ledger.
- No `EarlyExecutionObservation` or any other pre-fill execution signal.
- No HTTP endpoint, no `AbiExecutionEventOrchestrator`, no production
  composition wiring, no ABI webhook client, no ABI contract change.
- No Engine open-trade call and no change to `OpenTradeContextUnavailable`
  fail-closed routing.
- No outbox, retry, or durable deduplication of fill events — this change
  has no I/O at all.
- No general-purpose timeframe-duration engine for the rest of Runtime;
  every other module keeps treating `timeframe`/`base_timeframe` as an
  opaque, exact-match string per the ratified `deployment-selector` and
  `http-closed-bar` specs.

## Decisions

### `FrozenExecutedEntryContext` lives alongside `CurrentTradeCycle`

**Decision**: Add `FrozenExecutedEntryContext` to
`runtime/state/models.py`, next to `AppliedEntryPackage` and
`CurrentTradeCycle`, rather than to the new `runtime/first_fill/` package.

**Rationale**: It is a nested state value persisted as part of the
strategy-instance aggregate, exactly like `AppliedEntryPackage`. Keeping all
persisted-state shapes in one module matches the existing precedent and
keeps the repository's save/load contract (`strategy-instance-runtime-
state-repository`) unaffected by where the pure transition logic that
*produces* the value happens to live.

**Alternative considered**: Define it in the new `runtime/first_fill/`
package next to the transition that constructs it. Rejected: it would split
`CurrentTradeCycle`'s complete persisted shape across two modules for no
behavioral benefit, and would force the repository/model tests to import
across packages.

### New `runtime/first_fill/` package for the pure logic

**Decision**: Add `runtime/first_fill/alignment.py` (the alignment helper),
`runtime/first_fill/state_applier.py` (`apply_first_fill`), and
`runtime/first_fill/errors.py` (`FirstFillInvariantError`), mirroring the
existing `runtime/entry_reconciliation/` package shape
(`models.py`/`errors.py`/`reconciliation.py`/`state_applier.py`/
`command_builder.py`).

**Rationale**: `I5`'s future `AbiExecutionEventOrchestrator` will import
from this package the same way `EntryReconciliationOrchestrator` imports
from `entry_reconciliation`, giving `I5` the same thin-wiring shape as the
already-implemented reconciliation orchestrator.

### Two-tier error model: plain `ValueError`/`TypeError` vs. `FirstFillInvariantError`

**Decision**: `align_first_fill_to_entry_bar` raises plain `ValueError` for
malformed primitive input (`first_fill_at_ms` not a positive `int`,
`base_timeframe` not in the supported set), exactly like `DesiredEntry`,
`AppliedEntryPackage`, `RegisteredSpecSnapshot`, and
`StrategyInstanceRuntimeState` already do in their own `__post_init__`.
`apply_first_fill` reserves the new `FirstFillInvariantError` (mirroring
`EntryReconciliationInvariantError`) strictly for cross-object domain-
invariant violations that only the transition itself can detect: no current
trade cycle, a `trade_cycle_id` that does not match the current cycle, a
computed `entry_bar_open_time_ms` earlier than
`desired_entry.source_plan_bar_open_time_ms`, and a conflicting retried
`first_fill_at_ms` for an already-frozen cycle. `apply_first_fill` lets
`ValueError`/`TypeError` from the alignment helper and from
`FrozenExecutedEntryContext` construction propagate unchanged — it does not
wrap them.

**Rationale**: This exactly mirrors the existing, established split in
`entry_reconciliation/state_applier.py`: value-object construction
(`AppliedEntryPackage`, `CurrentTradeCycle`) raises plain `ValueError`/
`TypeError`, while `EntryReconciliationInvariantError` is reserved for
`_apply`/`_replace`/`_cancel`-level cross-object checks
(`_require_cycle_identity`, `_require_matching_desired_entries`, etc.).
Introducing a second dedicated exception class for the alignment helper
would break that precedent for no benefit, since callers of a pure
validator already expect `ValueError`/`TypeError` throughout this codebase.

**Alternative considered**: One error type for everything in the
`first_fill` package. Rejected as inconsistent with the sibling
`entry_reconciliation` package's own two-tier convention, which this
package intentionally mirrors.

### Closed timeframe-duration whitelist, scoped only to this helper

**Decision**: `alignment.py` defines a small, explicit
`_SUPPORTED_TIMEFRAME_DURATIONS_MS` mapping (`1m`, `3m`, `5m`, `15m`, `30m`,
`1h`, `2h`, `4h`, `6h`, `12h`, `1d`) used only by
`align_first_fill_to_entry_bar`. An unrecognized `base_timeframe` raises
`ValueError` — fail closed, never a best-effort parse.

**Rationale**: Repository-wide, `timeframe`/`base_timeframe` is treated as
an opaque, case-sensitive, exact-match string with no duration semantics
(`deployment-selector`, `http-closed-bar`, identity derivation) — this is a
deliberate, documented non-goal for the rest of Runtime (Market Data
Service owns candle-grid alignment upstream). This change is the first and
only place Runtime needs to turn a timeframe into a duration, and it does
so with the smallest closed set that covers every `base_timeframe` value
currently used in fixtures/config (`5m`, `15m`) plus the standard linear
exchange intervals, rather than inventing a generic parser
(`"\d+[mhd]"`-style parsing was considered and rejected — an unbounded
parser would silently accept values no deployment or exchange actually
uses, e.g. `"7m"`, undermining the fail-closed intent). Extending the table
later is additive and non-breaking.

**Alternative considered**: A generic `^(\d+)(m|h|d)$` regex parser instead
of an explicit table. Rejected: a closed enumeration gives an exact,
testable "supported" boundary consistent with this codebase's fail-closed
style, and the exchange's actual set of tradeable intervals is small and
already effectively fixed.

### `entry_bar_open_time_ms >= desired_entry.source_plan_bar_open_time_ms` is an `apply_first_fill` check, not an alignment-helper check

**Decision**: `align_first_fill_to_entry_bar(first_fill_at_ms,
base_timeframe)` does not take `desired_entry` and cannot perform this
check itself. `apply_first_fill` performs it after computing
`entry_bar_open_time_ms`, using the current cycle's applied
`DesiredEntry.source_plan_bar_open_time_ms`, and raises
`FirstFillInvariantError` on violation.

**Rationale**: An entry bar strictly before the bar that produced the
desired entry is impossible under correct ABI/Engine behavior and signals a
Runtime/ABI state divergence — the same fail-closed posture this codebase
already applies to `unknown_trade_cycle_binding` in `open-position-
resolver`. Keeping the helper's signature to exactly the two inputs the
task names (`first_fill_at_ms`, `base_timeframe`) also keeps it reusable
without requiring a `DesiredEntry` in hand.

### NO_OP returns the identical input `state` object; conflicting retry fails closed

**Decision**: When `current_trade_cycle.frozen_entry_context` is already
set with the same `first_fill_at_ms` as the call, `apply_first_fill`
returns the exact same `state` reference unchanged (not a
domain-equivalent copy). When it is set with a **different**
`first_fill_at_ms`, `apply_first_fill` raises `FirstFillInvariantError`
without mutating or replacing anything.

**Rationale**: Matches the task's explicit NO_OP/fail-closed rules and
gives the clearest possible test assertion (`is` identity) for the no-op
path, while the retried-conflict path mirrors the existing "preserve state
after contradictory formal success" invariant already ratified for
`entry_reconciliation`'s confirmation application.

### Freezing copies the existing `DesiredEntry` object, not a new copy

**Decision**: `FrozenExecutedEntryContext.desired_entry` is set to
`current_trade_cycle.applied_entry_package.applied_desired_entry` directly
(same immutable object reference), not a reconstructed or deep-copied
value.

**Rationale**: `DesiredEntry` is already an immutable, frozen, slotted
dataclass; nothing about freezing requires constructing a new instance.
Referencing the same object gives a trivial, unambiguous "this is exactly
what was applied" test assertion.

## Risks / Trade-offs

- **[Risk]** The closed timeframe table could omit a `base_timeframe` a
  future deployment legitimately uses (e.g. `2m`). → **Mitigation**:
  `align_first_fill_to_entry_bar` fails closed with a clear `ValueError`
  rather than silently misaligning; extending the table is a small,
  additive, low-risk follow-up change, not a breaking one.
- **[Risk]** `CurrentTradeCycle` gaining a new optional field is a
  **BREAKING** change to any code that asserts its exhaustive field set
  (already true of the ratified `current-trade-cycle-state` spec's
  "Exclude deferred execution state" scenario). → **Mitigation**: the
  `current-trade-cycle-state` spec delta in this change explicitly updates
  that scenario; no other ratified spec asserts `CurrentTradeCycle`'s
  exhaustive shape (confirmed by search across `openspec/specs/`).
- **[Trade-off]** This change intentionally ships a `CurrentTradeCycle`
  that cannot yet be produced or consumed by any orchestrator (no caller of
  `apply_first_fill` exists until `I5`). → **Accepted**: this is the
  explicit point of the split described in the proposal's "Why" — a
  reviewable, independently correct foundation before the larger
  orchestration change.

## Migration Plan

Additive, in-process, no persisted data to migrate (Live V1 state is
in-memory only per `strategy-instance-runtime-state-repository`). No
rollback beyond reverting the commit: the new field defaults to absent
behaviorally (nothing constructs a non-null `frozen_entry_context` until a
future `I5` caller exists). `frozen_entry_context` is added as the third
field with a default of `None`, after the two existing required fields
(`trade_cycle_id`, `applied_entry_package`); every existing two-positional-
argument and keyword-argument call site across production code and tests
(`entry_reconciliation/state_applier.py`, `test_state_models.py`,
`test_state_repository.py`, `test_semantic_pipeline.py`,
`entry_reconciliation_orchestrator/`, `entry_reconciliation/`,
`orchestrator/test_closed_bar_runtime_orchestration.py`) remains valid
unchanged.

## Open Questions

- None blocking this change. `executed_entry_price` / average-price
  handling, the fill-quantity lifecycle, and `AbiExecutionEventOrchestrator`
  wiring remain open questions explicitly deferred to the future `I5`
  design, per `runtime-abi-entry-reconciliation-master-plan.md` §17/§22.
