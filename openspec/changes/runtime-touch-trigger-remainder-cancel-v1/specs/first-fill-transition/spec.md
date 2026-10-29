## MODIFIED Requirements

### Requirement: apply_first_fill freezes the entry context exactly once per trade cycle
`apply_first_fill(state, trade_cycle_id, first_fill_at_ms, *, order_lifetime_bars=None)` SHALL require an
existing `CurrentTradeCycle` on `state` whose `trade_cycle_id` matches the
supplied `trade_cycle_id`, and on the first successful call for that cycle
SHALL return a new immutable `StrategyInstanceRuntimeState` whose current
trade cycle carries a `FrozenExecutedEntryContext` built from the currently
applied `DesiredEntry`, the supplied `first_fill_at_ms`, the aligned
`entry_bar_open_time_ms`, and `entry_order_expires_at_bar`. When
`order_lifetime_bars` is an integer (`touch_trigger`), `entry_order_expires_at_bar`
SHALL equal `DesiredEntry.source_plan_bar_open_time_ms + (order_lifetime_bars + 2) ×
timeframe_ms` of the registered base timeframe — the same value, from the same shared
function, that `touch_trigger` entry reconciliation uses as the order's expiry; it is
counted from the original signal, never from the fill. When `order_lifetime_bars` is
`None` (`ema_anchor`), `entry_order_expires_at_bar` SHALL be `null`. Every caller that
freezes a first fill (bar processing, the ABI first-fill event, the operator commands and the
uncertain-state resolver) SHALL pass the configured `order_lifetime_bars` in `touch_trigger`
and `None` in `ema_anchor`, so the boundary does not depend on which path saw the fill first.

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

#### Scenario: touch_trigger freezes the expiry from the signal bar
- **WHEN** the base timeframe is `5m`, `order_lifetime_bars` is `3`, the applied
  `DesiredEntry.source_plan_bar_open_time_ms` is 12:00, and the first fill is at 12:07
- **THEN** `entry_order_expires_at_bar` is 12:25 (12:00 + 5 × 5m)
- **AND** a first fill at 12:22 gives the same value

#### Scenario: ema_anchor freezes no expiry
- **WHEN** `apply_first_fill` is called with `order_lifetime_bars` `None`
- **THEN** `entry_order_expires_at_bar` is `null`
