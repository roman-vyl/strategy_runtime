## ADDED Requirements

### Requirement: Orchestrator supplies the touch-trigger lifetime inputs
`EntryReconciliationOrchestrator` SHALL receive `order_lifetime_bars` at
construction. In `touch_trigger` it SHALL be a non-negative non-boolean
integer, otherwise construction fails; in `ema_anchor` it is ignored. In
`touch_trigger`, `execute` SHALL pass `current_bar_open_time_ms` = the
projection's committed bar open time, `timeframe_ms` = the duration of the
projection's deployment `base_timeframe`, and `order_lifetime_bars` to
`touch_trigger_entry_reconciliation`. A resulting `Cancel` or `Replace`
SHALL execute through the same shared code as in `ema_anchor`.

#### Scenario: Expiry cancel through the shared path
- **WHEN** the mode is `touch_trigger` and the held entry is expired
- **AND** the projection's desired entry is null
- **THEN** the orchestrator saves the pending-entry-recovery marker for the
  current cycle and sends exactly one CANCEL for it

#### Scenario: Expiry replace through the shared path
- **WHEN** the mode is `touch_trigger` and the held entry is expired
- **AND** the projection carries a desired entry for the processed bar
- **THEN** the orchestrator executes confirmed CANCEL then APPLY with a newly
  reserved `trade_cycle_id`

#### Scenario: Missing lifetime in touch_trigger
- **WHEN** the orchestrator is constructed with mode `touch_trigger` and no
  valid `order_lifetime_bars`
- **THEN** construction fails with an error
