## ADDED Requirements

### Requirement: Entry-bar alignment floors a fill timestamp to its containing candle
`align_first_fill_to_entry_bar(first_fill_at_ms, base_timeframe)` SHALL
return `first_fill_at_ms - (first_fill_at_ms % duration_ms)`, where
`duration_ms` is the millisecond duration of a `base_timeframe` supported by
Runtime's small closed set of supported timeframes.

#### Scenario: Align a fill that occurs inside a candle
- **WHEN** `first_fill_at_ms` falls strictly between two consecutive bar
  boundaries for `base_timeframe`
- **THEN** the helper returns the most recent boundary at or before
  `first_fill_at_ms`, rounding down

#### Scenario: Align a fill that occurs exactly on a candle boundary
- **WHEN** `first_fill_at_ms` already equals a bar boundary for
  `base_timeframe`
- **THEN** the helper returns `first_fill_at_ms` unchanged

#### Scenario: Every returned alignment is exactly on a bar boundary
- **WHEN** the helper returns `entry_bar_open_time_ms` for any accepted
  input
- **THEN** `entry_bar_open_time_ms` is an exact multiple of the resolved
  timeframe duration
- **AND** `entry_bar_open_time_ms` is less than or equal to
  `first_fill_at_ms`

#### Scenario: Reject a non-positive or non-integer fill timestamp
- **WHEN** `first_fill_at_ms` is zero, negative, or not an integer
- **THEN** the helper raises `ValueError` before performing any alignment
  arithmetic

#### Scenario: Reject an unsupported timeframe
- **WHEN** `base_timeframe` is not one of Runtime's small closed set of
  supported timeframes
- **THEN** the helper raises `ValueError` and performs no alignment
  arithmetic

### Requirement: The first-fill transition reads the base timeframe only from registered Runtime state
`apply_first_fill` SHALL resolve `base_timeframe` exclusively from
`state.registered_spec_snapshot.base_timeframe` when calling
`align_first_fill_to_entry_bar`, and SHALL NOT accept or derive a timeframe
from any ABI event field or other caller-supplied value.

#### Scenario: Use the registered spec snapshot's timeframe
- **WHEN** `apply_first_fill` computes `entry_bar_open_time_ms`
- **THEN** it calls `align_first_fill_to_entry_bar` with
  `state.registered_spec_snapshot.base_timeframe`
- **AND** no other source of timeframe information is consulted

### Requirement: apply_first_fill freezes the entry context exactly once per trade cycle
`apply_first_fill(state, trade_cycle_id, first_fill_at_ms)` SHALL require an
existing `CurrentTradeCycle` on `state` whose `trade_cycle_id` matches the
supplied `trade_cycle_id`, and on the first successful call for that cycle
SHALL return a new immutable `StrategyInstanceRuntimeState` whose current
trade cycle carries a `FrozenExecutedEntryContext` built from the currently
applied `DesiredEntry`, the supplied `first_fill_at_ms`, and the aligned
`entry_bar_open_time_ms`.

#### Scenario: Freeze the context on the first fill
- **WHEN** `state.current_trade_cycle.trade_cycle_id` equals
  `trade_cycle_id` and `frozen_entry_context` is still null
- **THEN** `apply_first_fill` returns a new state whose current trade
  cycle's `frozen_entry_context` contains the currently applied
  `DesiredEntry`, the exact supplied `first_fill_at_ms`, and the
  `entry_bar_open_time_ms` computed by `align_first_fill_to_entry_bar`

#### Scenario: Freeze exactly the currently applied desired entry
- **WHEN** the transition freezes a context
- **THEN** `frozen_entry_context.desired_entry` equals
  `current_trade_cycle.applied_entry_package.applied_desired_entry`
  unchanged
- **AND** no other or reconstructed `DesiredEntry` is substituted

#### Scenario: Successful freezing does not mutate the input state
- **WHEN** `apply_first_fill` returns successfully
- **THEN** the `StrategyInstanceRuntimeState` and `CurrentTradeCycle`
  objects passed in remain unmodified and domain-value-equivalent to their
  pre-call snapshots
- **AND** the returned state is a distinct new immutable object

#### Scenario: Fail closed with no state or no current trade cycle
- **WHEN** `state` is not a `StrategyInstanceRuntimeState`, or
  `state.current_trade_cycle` is null
- **THEN** `apply_first_fill` raises `FirstFillInvariantError`
- **AND** no `FrozenExecutedEntryContext` is constructed

#### Scenario: Fail closed on a trade_cycle_id mismatch
- **WHEN** the supplied `trade_cycle_id` does not equal
  `state.current_trade_cycle.trade_cycle_id`
- **THEN** `apply_first_fill` raises `FirstFillInvariantError`
- **AND** the input state remains unmodified

#### Scenario: Fail closed when the entry bar precedes the plan bar
- **WHEN** the computed `entry_bar_open_time_ms` is less than the currently
  applied `DesiredEntry.source_plan_bar_open_time_ms`
- **THEN** `apply_first_fill` raises `FirstFillInvariantError`
- **AND** no `FrozenExecutedEntryContext` is constructed or stored

#### Scenario: Propagate alignment failures unwrapped
- **WHEN** `align_first_fill_to_entry_bar` raises `ValueError` for a
  non-positive `first_fill_at_ms` or an unsupported `base_timeframe`
- **THEN** `apply_first_fill` lets that `ValueError` propagate unwrapped
- **AND** does not translate it into `FirstFillInvariantError`

### Requirement: A repeated identical first fill is a no-op; a conflicting one fails closed
Once `current_trade_cycle.frozen_entry_context` is set for a trade cycle,
`apply_first_fill` SHALL return the identical input `state` object,
unmodified, when called again for that same cycle with the same
`first_fill_at_ms`, and SHALL raise `FirstFillInvariantError` without
mutating state when called with a different `first_fill_at_ms` for that same
cycle.

#### Scenario: The same fill retried is a no-op
- **WHEN** `apply_first_fill` is called again with the exact
  `first_fill_at_ms` already frozen for the matching trade cycle
- **THEN** it returns the exact same `state` object reference, unmodified
- **AND** it constructs no new `FrozenExecutedEntryContext` and performs no
  alignment call

#### Scenario: A conflicting retried fill fails closed
- **WHEN** `apply_first_fill` is called with a `first_fill_at_ms` that
  differs from the one already frozen for the matching trade cycle
- **THEN** it raises `FirstFillInvariantError`
- **AND** the input state remains unmodified and domain-value-equivalent to
  its pre-call snapshot
- **AND** the originally frozen context is neither replaced nor cleared

### Requirement: apply_first_fill introduces no execution-phase or quantity lifecycle
`apply_first_fill` SHALL NOT introduce, read, or require an execution
`phase`, filled or remaining quantity, average execution price, a fill
ledger, or an `EarlyExecutionObservation`.

#### Scenario: No phase or quantity state appears after freezing
- **WHEN** `apply_first_fill` returns successfully
- **THEN** the resulting state contains no `phase` field, no filled or
  remaining quantity, no average execution price, and no fill ledger
  anywhere in the current trade cycle
