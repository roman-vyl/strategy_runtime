## ADDED Requirements

### Requirement: Resolver carries the entry order identifiers transiently
`PositionResolvedStrategyInstanceRuntimeState` SHALL carry `entry_order_link_id` and `entry_order_id` from the lookup response unchanged. With no current trade cycle, or a closed position, both SHALL be `None`. They SHALL NOT be persisted in Runtime state and SHALL NOT be used in any decision.

#### Scenario: Open position
- **WHEN** the lookup reports an open position with both identifiers
- **THEN** the resolved state carries them unchanged

#### Scenario: No current cycle
- **WHEN** the state has no current trade cycle
- **THEN** the resolved state carries both identifiers as `None` and no lookup is made
