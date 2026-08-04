## 1. State Models

- [x] 1.1 Add `FrozenExecutedEntryContext` to `runtime/state/models.py`
  (`desired_entry: DesiredEntry`, `first_fill_at_ms: int`,
  `entry_bar_open_time_ms: int`), with `__post_init__` validation using
  strict type checks (`type(x) is int`, not `isinstance`, so `bool` is
  rejected since `bool` is a subclass of `int` in Python):
  `type(desired_entry) is DesiredEntry`; `type(first_fill_at_ms) is int` and
  `first_fill_at_ms > 0`; `type(entry_bar_open_time_ms) is int` and
  `entry_bar_open_time_ms >= 0` and `entry_bar_open_time_ms <=
  first_fill_at_ms`. Raise `ValueError`/`TypeError` on any violation.
- [x] 1.2 Add `frozen_entry_context: FrozenExecutedEntryContext | None =
  None` as the third field on `CurrentTradeCycle`, after the existing
  `trade_cycle_id`/`applied_entry_package` fields, with a
  `__post_init__` type check (`None` or `FrozenExecutedEntryContext`).
- [x] 1.3 Confirm every existing `CurrentTradeCycle(...)` call site
  (`entry_reconciliation/state_applier.py` and all test fixtures) remains
  valid unchanged with the new trailing defaulted field.

## 2. Entry-Bar Alignment Helper

- [x] 2.1 Create `runtime/first_fill/__init__.py`.
- [x] 2.2 Create `runtime/first_fill/alignment.py` with a module-level
  closed mapping `_SUPPORTED_TIMEFRAME_DURATIONS_MS` for `1m`, `5m`,
  `15m`, `1h`, `4h`, `1d`.
- [x] 2.3 Implement `align_first_fill_to_entry_bar(first_fill_at_ms: int,
  base_timeframe: str) -> int`: raise `ValueError` when
  `type(first_fill_at_ms) is not int` (strict check, `bool` rejected) or
  `first_fill_at_ms <= 0`; raise `ValueError` when `base_timeframe` is not
  in the supported mapping; otherwise return `first_fill_at_ms -
  (first_fill_at_ms % duration_ms)`.

## 3. Pure First-Fill Transition

- [x] 3.1 Create `runtime/first_fill/errors.py` with
  `FirstFillInvariantError(RuntimeError)`, mirroring
  `entry_reconciliation/errors.py`'s `EntryReconciliationInvariantError`.
- [x] 3.2 Create `runtime/first_fill/state_applier.py` implementing
  `apply_first_fill(state: StrategyInstanceRuntimeState, trade_cycle_id:
  str, first_fill_at_ms: int) -> StrategyInstanceRuntimeState`:
  - validate input types (`state` is `StrategyInstanceRuntimeState`,
    `trade_cycle_id` is a non-empty `str`),
    raising `FirstFillInvariantError` on failure;
  - require `state.current_trade_cycle is not None`, raising
    `FirstFillInvariantError` otherwise;
  - require `state.current_trade_cycle.trade_cycle_id == trade_cycle_id`,
    raising `FirstFillInvariantError` otherwise;
  - if `frozen_entry_context` is already set: return `state` unchanged (the
    identical object reference) when `first_fill_at_ms` matches; raise
    `FirstFillInvariantError` when it differs;
  - otherwise call `align_first_fill_to_entry_bar(first_fill_at_ms,
    state.registered_spec_snapshot.base_timeframe)` and let any
    `ValueError` it raises propagate unwrapped;
  - read `desired_entry =
    state.current_trade_cycle.applied_entry_package.applied_desired_entry`;
    raise `FirstFillInvariantError` if `entry_bar_open_time_ms <
    desired_entry.source_plan_bar_open_time_ms`;
  - construct `FrozenExecutedEntryContext(desired_entry=desired_entry,
    first_fill_at_ms=first_fill_at_ms,
    entry_bar_open_time_ms=entry_bar_open_time_ms)`;
  - return `dataclasses.replace(state, current_trade_cycle=
    dataclasses.replace(state.current_trade_cycle,
    frozen_entry_context=frozen_context))`.

## 4. Unit Tests: Alignment

- [x] 4.1 Create `tests/unit/runtime/first_fill/__init__.py` and
  `tests/unit/runtime/first_fill/test_alignment.py`.
- [x] 4.2 Test: a fill timestamp inside a candle rounds down to the
  candle's open time.
- [x] 4.3 Test: a fill timestamp exactly on a candle boundary stays on that
  boundary.
- [x] 4.4 Test: every returned alignment is an exact multiple of the
  resolved timeframe duration and `<= first_fill_at_ms` (property-style
  check across multiple supported timeframes and offsets).
- [x] 4.5 Test: a non-positive or non-integer `first_fill_at_ms` raises
  `ValueError`.
- [x] 4.6 Test: an unsupported `base_timeframe` raises `ValueError`.

## 5. Unit Tests: apply_first_fill

- [x] 5.1 Create `tests/unit/runtime/first_fill/test_state_applier.py`
  with a shared fixture building a `StrategyInstanceRuntimeState` with a
  registered `base_timeframe` and an existing `CurrentTradeCycle`
  (`frozen_entry_context=None`).
- [x] 5.2 Test: the first fill successfully freezes the context with the
  currently applied `DesiredEntry`, the supplied `first_fill_at_ms`, and
  the aligned `entry_bar_open_time_ms`.
- [x] 5.3 Test: `apply_first_fill` reads `base_timeframe` from
  `state.registered_spec_snapshot.base_timeframe` (assert via a spy/stub
  alignment call or via two states differing only in `base_timeframe`
  producing different `entry_bar_open_time_ms` for the same
  `first_fill_at_ms`).
- [x] 5.4 Test: `state is None`/wrong type, or `state.current_trade_cycle
  is None`, raises `FirstFillInvariantError`.
- [x] 5.5 Test: a `trade_cycle_id` that does not match
  `state.current_trade_cycle.trade_cycle_id` raises
  `FirstFillInvariantError`.
- [x] 5.6 Test: an unsupported `base_timeframe` on the registered spec
  snapshot propagates `ValueError` unwrapped from
  `align_first_fill_to_entry_bar`.
- [x] 5.7 Test: calling `apply_first_fill` again with the identical
  `first_fill_at_ms` for an already-frozen cycle returns the exact same
  `state` object (`is` identity) and is a no-op.
- [x] 5.8 Test: calling `apply_first_fill` again with a different
  `first_fill_at_ms` for an already-frozen cycle raises
  `FirstFillInvariantError` and leaves the original frozen context intact.
- [x] 5.9 Test: the frozen `desired_entry` is exactly
  `current_trade_cycle.applied_entry_package.applied_desired_entry`
  (identity/equality check).
- [x] 5.10 Test: the input `state` and its `current_trade_cycle` are not
  mutated by a successful call (snapshot-equality check against a pre-call
  copy, per the existing `entry_reconciliation` test convention).
- [x] 5.11 Test: an `entry_bar_open_time_ms` computed earlier than the
  applied `DesiredEntry.source_plan_bar_open_time_ms` raises
  `FirstFillInvariantError` and freezes nothing.

## 5.5. Entry Reconciliation Protection

- [x] 5.12 Modify `decide_entry_reconciliation` in
  `runtime/entry_reconciliation/reconciliation.py` to check, immediately after
  the existing `new_desired_entry` type check and before computing
  `acknowledged_desired_entry` or evaluating the four-way decision table:
  if `current_trade_cycle is not None and current_trade_cycle.frozen_entry_context
  is not None`, raise `EntryReconciliationInvariantError`. This runs before
  `build_entry_reconciliation_command` and before
  `EntryReconciliationExecutionPort.execute` are ever reached, so no
  `EntryReconciliationCommand` is built and no ABI entry-package command is
  sent for a trade cycle whose entry is already frozen. Do not modify
  `apply_success_confirmation`, `command_builder.py`, or any other file in
  `entry_reconciliation/` or `entry_reconciliation_orchestrator/`.

## 5.6. Unit Tests: Entry Reconciliation Protection

- [x] 5.13 Add tests in `tests/unit/runtime/entry_reconciliation/
  test_reconciliation.py` (or equivalent) covering `decide_entry_reconciliation`
  with a `current_trade_cycle.frozen_entry_context` set:
  - a `new_desired_entry` equivalent to the acknowledged applied desired
    entry raises `EntryReconciliationInvariantError` (not `NoOp`);
  - a `new_desired_entry` different from the acknowledged applied desired
    entry raises `EntryReconciliationInvariantError` (not `Replace`);
  - `new_desired_entry = None` raises `EntryReconciliationInvariantError`
    (not `Cancel`).
- [x] 5.14 Add an orchestrator-level test in
  `tests/unit/runtime/entry_reconciliation_orchestrator/` using a fake
  `EntryReconciliationExecutionPort` that fails the test if `execute` is
  called: call `EntryReconciliationOrchestrator.execute` with a projection
  whose source state has a `current_trade_cycle.frozen_entry_context` set,
  assert `EntryReconciliationInvariantError` propagates, assert the fake
  execution port recorded zero calls, and assert the source state is
  returned unmodified (no repository save path exercised).

## 6. Verification

- [x] 6.1 Run `make verify` (or the project's configured lint/type/test
  target) and confirm no regression in existing `runtime/state`,
  `entry_reconciliation`, `entry_reconciliation_orchestrator`, or
  `orchestrator` test suites caused by the new `CurrentTradeCycle` field and
  the new frozen-entry-context guard in `decide_entry_reconciliation`.
- [x] 6.2 Run `npm exec -- openspec validate "runtime-first-fill-state-foundation-v1"
  --type change --strict` and resolve any reported issues before archiving.
