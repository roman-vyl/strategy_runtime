## ADDED Requirements

### Requirement: Runtime applies the first-fill transition before routing an open position
For a resolved open position, `StrategyRuntimeOrchestrator.process(...)`
SHALL apply the existing first-fill transition inside the already-held
keyed critical section before calling `StrategyUseCaseRouter`. A later
router or Engine failure SHALL NOT revert an already-saved result of this
transition.

#### Scenario: A changed transition result is saved and routed
- **WHEN** the transition produces a changed state for the resolved open
  position
- **THEN** the orchestrator saves that state through the repository before
  calling the router
- **AND** the router receives the saved state

#### Scenario: An unchanged transition result is not saved
- **WHEN** the transition returns its input state unchanged
- **THEN** the orchestrator does not call repository `save(...)`
- **AND** routing proceeds with the unchanged resolved state

#### Scenario: A transition failure stops the cycle before routing
- **WHEN** the transition raises
- **THEN** that failure propagates out of `process(...)`
- **AND** the router is not called and no save occurs
