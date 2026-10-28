## Why

When Runtime ends an entry attempt without a fill it only clears its durable state; nothing is written to the processing journal. A cancelled, replaced-away, disabled or recovered-absent entry order therefore leaves the last `entry_package_applied` of its cycle looking alive forever. The Central Journal and the dashboard cannot say "this entry order is gone". Together with the read-only trade-state route (`runtime-strategy-trading-state-v1`, current state) the dashboard also needs the history of the same transitions, written from the same place where the state changes.

## What Changes

- New processing-journal event `entry_cycle_ended`, appended after the durable save of every state change that removes a current cycle which never filled:
  - `cancelled`: a confirmed CANCEL in bar processing (also the CANCEL step of a Replace, which is followed by a new `entry_package_applied`);
  - `disabled`: the enabled-control cancel step after a confirmed exact absence;
  - `terminal_without_fill`: the uncertain-state resolver found the entry terminal without a fill;
  - `exact_absent`: the resolver's one corrective CANCEL came back as exact formal absence.
- Payload: `trade_cycle_id`, `bar_open_time_ms` (an integer in bar processing, `null` when the change happens outside a bar: disabled and both resolver reasons), `reason` (one of the four values above).
- Nothing else changes: no new state, no route, no ABI or Engine change, no new journal for filled cycles (`trade_cycle_opened` and `trade_cycle_closed` already exist).

## Non-goals

- Recovery markers are not journaled; they stay visible through the trade-state route only.
- `terminal_after_fill` in the resolver is not covered: that cycle did fill, and its closure is a separate question.
- `entry_package_declined` is untouched.

## Capabilities

### Modified Capabilities

- `processing-journal`: new `entry_cycle_ended` event.

## Impact

`utility/processing_journal/{models.py,jsonl_adapter.py}`, a journal port next to `EntryDeclinedJournalPort`, the three state-clearing paths (`entry_reconciliation_orchestrator`, `enabled_control/cancel_step.py`, `uncertain_exchange_state_resolver/resolver.py`), `bootstrap/application.py`, tests. Rollout: Journal first (it must accept the type), then Runtime; Runtime writes the event even if Journal ignores it, so order only matters for visibility.
