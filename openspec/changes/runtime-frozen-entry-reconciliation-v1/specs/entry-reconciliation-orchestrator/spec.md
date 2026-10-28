## ADDED Requirements

### Requirement: Orchestrator selects the decision policy by live-entry mode
`EntryReconciliationOrchestrator` SHALL receive `live_entry_mode` at
construction (default `ema_anchor`) and reject a value outside
`ema_anchor`, `touch_trigger`. `execute` SHALL obtain its decision from
`decide_entry_reconciliation` in `ema_anchor` and from
`touch_trigger_entry_reconciliation` in `touch_trigger`, with the same two
inputs. Everything after the decision (identity reservation, command
construction, the pending-entry-recovery marker save, execution, Replace
decomposition, confirmation application, journals) SHALL be the same code for
both modes. The mode SHALL NOT create a second execution path.

#### Scenario: Held entry is not touched in touch_trigger
- **WHEN** the mode is `touch_trigger`
- **AND** the source state has an acknowledged applied entry
- **AND** the projection's desired entry is null or differs from it
- **THEN** the orchestrator does not invoke `TradeCycleIdFactory`, the command
  builder, the repository or the execution port
- **AND** returns state whose acknowledged desired entry and `trade_cycle_id`
  are unchanged

#### Scenario: First entry in touch_trigger
- **WHEN** the mode is `touch_trigger`
- **AND** the source state has no current trade cycle
- **AND** the projection carries a desired entry
- **THEN** the orchestrator executes `Apply` exactly as in `ema_anchor`,
  including the pending-entry-recovery marker save before the port call

#### Scenario: ema_anchor unchanged
- **WHEN** the mode is `ema_anchor` or not given
- **AND** the source state has an acknowledged applied entry
- **THEN** a null projection executes `Cancel` and a different projection
  executes `Replace`, as before this change

#### Scenario: Invalid mode
- **WHEN** the orchestrator is constructed with a mode other than
  `ema_anchor` or `touch_trigger`
- **THEN** construction fails with an error
