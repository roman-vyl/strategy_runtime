## ADDED Requirements

### Requirement: Exact enabled stream selection
The deployment selector MUST select only accepted deployments whose instrument and base timeframe exactly and case-sensitively match the committed-bar event and whose deployment-local `enabled` flag is `true`.

#### Scenario: Enabled exact match
- **GIVEN** an accepted deployment with `enabled = true`
- **AND** exact instrument and base-timeframe equality with the committed bar
- **WHEN** selection runs
- **THEN** the deployment SHALL be selected

#### Scenario: Disabled exact match
- **GIVEN** an accepted deployment with `enabled = false`
- **WHEN** selection runs
- **THEN** the deployment SHALL NOT be selected

#### Scenario: Market coordinate mismatch
- **GIVEN** an enabled deployment whose instrument or base timeframe differs
- **WHEN** selection runs
- **THEN** the deployment SHALL NOT be selected

#### Scenario: Case-only market coordinate mismatch
- **GIVEN** an enabled deployment whose instrument or base timeframe differs from the committed bar only by letter case
- **WHEN** selection runs
- **THEN** the deployment SHALL NOT be selected

### Requirement: Selection is pure and preserves catalog order
The deployment selector SHALL perform no I/O or activation reconciliation and SHALL preserve the relative catalog order of selected deployments.

#### Scenario: Repeated equivalent selection
- **WHEN** selection runs repeatedly with equivalent events and snapshots
- **THEN** it returns equivalent immutable `SelectedDeployment` values in the same relative order
- **AND** final dispatch sorting remains the responsibility of `CommittedBarOrchestrator`
