## 1. State Models

- [ ] 1.1 Add `FrozenExecutedEntryContext` to `runtime/state/models.py`
  (`desired_entry: DesiredEntry`, `first_fill_at_ms: int`,
  `entry_bar_open_time_ms: int`), with `__post_init__` validation:
  `desired_entry` must be `DesiredEntry`; `first_fill_at_ms` must be a
  strictly positive `int`; `entry_bar_open_time_ms` must be a non-negative
  `int` and `<= first_fill_at_ms`.
- [ ] 1.2 Add `frozen_entry_context: FrozenExecutedEntryContext | None =
  None` as the third field on `CurrentTradeCycle`, after the existing
  `trade_cycle_id`/`applied_entry_package` fields, with a
  `__post_init__` type check (`None` or `FrozenExecutedEntryContext`).
- [ ] 1.3 Confirm every existing `CurrentTradeCycle(...)` call site
  (`entry_reconciliation/state_applier.py` and all test fixtures) remains
  valid unchanged with the new trailing defaulted field.

## 2. Entry-Bar Alignment Helper

- [ ] 2.1 Create `runtime/first_fill/__init__.py`.
- [ ] 2.2 Create `runtime/first_fill/alignment.py` with a module-level
  closed mapping `_SUPPORTED_TIMEFRAME_DURATIONS_MS` for `1m`, `3m`, `5m`,
  `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d`.
- [ ] 2.3 Implement `align_first_fill_to_entry_bar(first_fill_at_ms: int,
  base_timeframe: str) -> int`: raise `ValueError` when `first_fill_at_ms`
  is not a strictly positive `int`; raise `ValueError` when
  `base_timeframe` is not in the supported mapping; otherwise return
  `first_fill_at_ms - (first_fill_at_ms % duration_ms)`.

## 3. Pure First-Fill Transition

- [ ] 3.1 Create `runtime/first_fill/errors.py` with
  `FirstFillInvariantError(RuntimeError)`, mirroring
  `entry_reconciliation/errors.py`'s `EntryReconciliationInvariantError`.
- [ ] 3.2 Create `runtime/first_fill/state_applier.py` implementing
  `apply_first_fill(state: StrategyInstanceRuntimeState, trade_cycle_id:
  str, first_fill_at_ms: int) -> StrategyInstanceRuntimeState`:
  - validate input types (`state` is `StrategyInstanceRuntimeState`,
    `trade_cycle_id` is a non-empty `str`, `first_fill_at_ms` is an `int`),
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

- [ ] 4.1 Create `tests/unit/runtime/first_fill/__init__.py` and
  `tests/unit/runtime/first_fill/test_alignment.py`.
- [ ] 4.2 Test: a fill timestamp inside a candle rounds down to the
  candle's open time.
- [ ] 4.3 Test: a fill timestamp exactly on a candle boundary stays on that
  boundary.
- [ ] 4.4 Test: every returned alignment is an exact multiple of the
  resolved timeframe duration and `<= first_fill_at_ms` (property-style
  check across multiple supported timeframes and offsets).
- [ ] 4.5 Test: a non-positive or non-integer `first_fill_at_ms` raises
  `ValueError`.
- [ ] 4.6 Test: an unsupported `base_timeframe` raises `ValueError`.

## 5. Unit Tests: apply_first_fill

- [ ] 5.1 Create `tests/unit/runtime/first_fill/test_state_applier.py`
  with a shared fixture building a `StrategyInstanceRuntimeState` with a
  registered `base_timeframe` and an existing `CurrentTradeCycle`
  (`frozen_entry_context=None`).
- [ ] 5.2 Test: the first fill successfully freezes the context with the
  currently applied `DesiredEntry`, the supplied `first_fill_at_ms`, and
  the aligned `entry_bar_open_time_ms`.
- [ ] 5.3 Test: `apply_first_fill` reads `base_timeframe` from
  `state.registered_spec_snapshot.base_timeframe` (assert via a spy/stub
  alignment call or via two states differing only in `base_timeframe`
  producing different `entry_bar_open_time_ms` for the same
  `first_fill_at_ms`).
- [ ] 5.4 Test: `state is None`/wrong type, or `state.current_trade_cycle
  is None`, raises `FirstFillInvariantError`.
- [ ] 5.5 Test: a `trade_cycle_id` that does not match
  `state.current_trade_cycle.trade_cycle_id` raises
  `FirstFillInvariantError`.
- [ ] 5.6 Test: an unsupported `base_timeframe` on the registered spec
  snapshot propagates `ValueError` unwrapped from
  `align_first_fill_to_entry_bar`.
- [ ] 5.7 Test: calling `apply_first_fill` again with the identical
  `first_fill_at_ms` for an already-frozen cycle returns the exact same
  `state` object (`is` identity) and is a no-op.
- [ ] 5.8 Test: calling `apply_first_fill` again with a different
  `first_fill_at_ms` for an already-frozen cycle raises
  `FirstFillInvariantError` and leaves the original frozen context intact.
- [ ] 5.9 Test: the frozen `desired_entry` is exactly
  `current_trade_cycle.applied_entry_package.applied_desired_entry`
  (identity/equality check).
- [ ] 5.10 Test: the input `state` and its `current_trade_cycle` are not
  mutated by a successful call (snapshot-equality check against a pre-call
  copy, per the existing `entry_reconciliation` test convention).
- [ ] 5.11 Test: an `entry_bar_open_time_ms` computed earlier than the
  applied `DesiredEntry.source_plan_bar_open_time_ms` raises
  `FirstFillInvariantError` and freezes nothing.

## 6. Verification

- [ ] 6.1 Run `make verify` (or the project's configured lint/type/test
  target) and confirm no regression in existing `runtime/state`,
  `entry_reconciliation`, `entry_reconciliation_orchestrator`, or
  `orchestrator` test suites caused by the new `CurrentTradeCycle` field.
- [ ] 6.2 Run `npm exec -- openspec validate --change
  runtime-first-fill-state-foundation-v1 --strict --no-interactive` and
  resolve any reported issues before archiving.
