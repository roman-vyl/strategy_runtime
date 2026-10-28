## ADDED Requirements

### Requirement: Live-entry mode reaches only entry reconciliation
Runtime composition SHALL pass `RuntimeConfig.live_entry_mode` to
`EntryReconciliationOrchestrator` and to no other component. No other
component's behaviour SHALL depend on the mode.

#### Scenario: Composed with touch_trigger
- **WHEN** the Runtime config carries `live_entry_mode = touch_trigger`
- **THEN** the composed `EntryReconciliationOrchestrator` uses
  `touch_trigger_entry_reconciliation`
- **AND** the router still calls the Engine live-entry projection on every
  processed closed bar

#### Scenario: Composed without a config file
- **WHEN** no Runtime config file exists
- **THEN** the composed `EntryReconciliationOrchestrator` uses
  `decide_entry_reconciliation`
