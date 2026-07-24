# strategy-runtime-orchestrator Specification

## Purpose

Define the scalar semantic orchestrator that coordinates one processing unit
through state get-or-create, open-position resolution, and typed Strategy Engine
projection while stopping before state application or execution.

## Requirements

### Requirement: Runtime coordinates one semantic processing unit through Engine projection
Strategy Runtime SHALL provide `StrategyRuntimeOrchestrator.process(...)` to
coordinate one `StrategyBarProcessingUnit` through state get-or-create,
open-position resolution, and use-case routing.

#### Scenario: Process one unit
- **WHEN** `process(...)` receives one `StrategyBarProcessingUnit`
- **THEN** it calls `StrategyInstanceRuntimeStateRepository.get_or_create(...)` once
- **AND** passes the returned state to `OpenPositionResolver`
- **AND** passes the resolved state and original processing unit to `StrategyUseCaseRouter`
- **AND** returns the resulting typed Engine projection

#### Scenario: Preserve the implemented stopping point
- **WHEN** `process(...)` returns a projection
- **THEN** the orchestrator has not applied the recipe to repository state
- **AND** has not created an ABI execution command
- **AND** has not interpreted Engine output as an exchange action

### Requirement: Runtime exposes the utility handoff dispatch contract
`StrategyRuntimeOrchestrator.dispatch(...)` SHALL adapt semantic processing to
the utility `StrategyCycleDispatcher` contract.

#### Scenario: Dispatch one unit successfully
- **WHEN** semantic processing completes without raising an error
- **THEN** `dispatch(...)` returns a successful `StrategyCycleDispatchOutcome`
- **AND** the outcome contains the processing unit's `strategy_instance_id`

#### Scenario: Propagate semantic failure
- **WHEN** repository lookup, position resolution, or Engine projection raises an error
- **THEN** `dispatch(...)` does not fabricate a successful projection
- **AND** the error propagates to the utility orchestration boundary
