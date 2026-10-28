## MODIFIED Requirements

### Requirement: Touch-trigger reconciliation holds the acknowledged entry
Runtime SHALL provide a pure decision function
`touch_trigger_entry_reconciliation(new_desired_entry, current_trade_cycle, *, current_bar_open_time_ms, timeframe_ms, order_lifetime_bars)`
that returns one of the existing closed decision variants. When no current
trade cycle exists it SHALL decide exactly as `decide_entry_reconciliation`
(`NoOp` for a null projection, `Apply` carrying the new desired entry
otherwise). When an acknowledged applied entry exists it SHALL compute
`expiration = held.source_plan_bar_open_time_ms + (order_lifetime_bars + 2) × timeframe_ms`
from the acknowledged (held) desired entry only, and treat the entry as
expired when `current_bar_open_time_ms + timeframe_ms >= expiration`. Before
expiry it SHALL return `NoOp` whatever the new desired entry is. When expired
it SHALL return `Cancel(trade_cycle_id)` if the new desired entry is null or
its `source_plan_bar_open_time_ms` differs from `current_bar_open_time_ms`,
and `Replace(trade_cycle_id, new_desired_entry)` otherwise, including when the
new desired entry is equivalent to the held one. It SHALL apply the same input
type checks and the same fail-closed check on
`current_trade_cycle.frozen_entry_context` as `decide_entry_reconciliation`,
and reject a negative or non-integer bar time, a non-positive or non-integer
timeframe, and a negative, boolean or non-integer lifetime.
`decide_entry_reconciliation` SHALL remain unchanged.

#### Scenario: First desired entry is applied
- **WHEN** `current_trade_cycle` is null
- **AND** the new desired entry is non-null
- **THEN** the decision is `Apply` carrying that desired entry unchanged

#### Scenario: Nothing to apply
- **WHEN** `current_trade_cycle` is null
- **AND** the new desired entry is null
- **THEN** the decision is `NoOp`

#### Scenario: Held entry before expiry
- **WHEN** an acknowledged applied entry with signal bar 12:00 exists
- **AND** `order_lifetime_bars` is 3 and the timeframe is 5m
- **AND** the processed bar opens at 12:05, 12:10 or 12:15
- **THEN** the decision is `NoOp` for a null, equal or different new desired
  entry

#### Scenario: Expired with no signal
- **WHEN** the same held entry exists
- **AND** the processed bar opens at 12:20 (closes at the 12:25 boundary)
- **AND** the new desired entry is null
- **THEN** the decision is `Cancel` carrying the current `trade_cycle_id`

#### Scenario: Expired with a fresh signal
- **WHEN** the same held entry exists
- **AND** the processed bar opens at 12:20
- **AND** the new desired entry has `source_plan_bar_open_time_ms` 12:20
- **THEN** the decision is `Replace` carrying the current `trade_cycle_id` and
  the new desired entry, also when it is equivalent to the held one

#### Scenario: Expired with a stale signal
- **WHEN** the held entry is expired on the processed bar
- **AND** the new desired entry's `source_plan_bar_open_time_ms` differs from
  the processed bar's open time
- **THEN** the decision is `Cancel`

#### Scenario: Zero lifetime is one bar
- **WHEN** `order_lifetime_bars` is 0 and the held signal bar opens at 12:00
- **THEN** the processed bar opening at 12:05 is already expired

#### Scenario: Skipped bars
- **WHEN** no bar was processed between the held entry and a processed bar
  that opens after the boundary
- **THEN** that processed bar decides `Cancel` or `Replace` as expired

#### Scenario: New signals do not extend the lifetime
- **WHEN** non-null desired entries for later bars arrive before expiry
- **THEN** the expiration is still computed from the held entry's
  `source_plan_bar_open_time_ms`

#### Scenario: Fail closed once the entry context is frozen
- **WHEN** `current_trade_cycle.frozen_entry_context` is not null
- **THEN** `touch_trigger_entry_reconciliation` raises
  `EntryReconciliationInvariantError`

#### Scenario: Pure function
- **WHEN** `touch_trigger_entry_reconciliation` executes
- **THEN** it performs no HTTP, ABI-port, repository, mutex, Engine, clock or
  identity-factory operation
