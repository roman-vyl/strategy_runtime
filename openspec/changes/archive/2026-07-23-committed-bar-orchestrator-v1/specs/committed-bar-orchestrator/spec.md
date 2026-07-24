## ADDED Requirements

### Requirement: Runtime exposes one committed-bar orchestration boundary
Strategy Runtime SHALL provide one `CommittedBarOrchestrator.process(committed_bar)` boundary that owns the top-level utility sequence for one accepted immutable `CommittedBarEvent`.

#### Scenario: Start committed-bar orchestration
- **WHEN** an upstream caller invokes the orchestrator with one committed-bar event
- **THEN** the orchestrator starts processing with that event only
- **AND** no trace identifier or processing context enters the orchestration object graph

#### Scenario: Keep transport outside the capability
- **WHEN** the orchestrator is constructed
- **THEN** HTTP routing and background scheduling remain outside this capability

### Requirement: The orchestrator delegates through four typed ports
The orchestrator SHALL coordinate deployment catalog, deployment selector, strategy-cycle dispatch, and processing-journal behavior through consumer-owned typed ports and SHALL NOT reproduce their internal rules.

#### Scenario: Coordinate one committed bar
- **WHEN** the orchestrator processes one committed-bar event
- **THEN** it records orchestration start
- **AND** obtains one current deployment catalog snapshot
- **AND** obtains one selected deployment tuple for the event and snapshot
- **AND** dispatches one processing unit for each selection
- **AND** records every unit outcome and the aggregate completion result

#### Scenario: Do not repeat upstream work per deployment
- **WHEN** several deployments are selected
- **THEN** catalog discovery and deployment selection each occur exactly once

#### Scenario: Exclude semantic and trading behavior
- **WHEN** the orchestrator processes a committed bar
- **THEN** it does not query ABI or Strategy Engine directly
- **AND** does not infer position state or Engine route
- **AND** does not create or modify trading orders

### Requirement: The orchestrator dispatches immutable strategy-bar processing units
The orchestrator SHALL create one immutable `StrategyBarProcessingUnit` containing exactly `strategy_instance_id`, the selected deployment, and the committed-bar event.

#### Scenario: Include only established utility data
- **WHEN** a processing unit is created
- **THEN** its identity equals the selected `strategy_instance_id`
- **AND** it contains the exact selected deployment and committed-bar event
- **AND** it contains no trace, processing context, Runtime state, Engine, ABI, order, receipt, or exchange data

#### Scenario: Dispatch through the typed boundary
- **WHEN** a processing unit is ready
- **THEN** the orchestrator passes it to `StrategyCycleDispatchPort.dispatch`

### Requirement: Dispatch order is deterministic
The orchestrator SHALL dispatch selected deployments sequentially in ascending `strategy_instance_id` order.

#### Scenario: Multiple selected deployments
- **WHEN** selections are supplied in any order
- **THEN** every selection is attempted exactly once in ascending stable-identity order

#### Scenario: Repeated equivalent input
- **WHEN** equivalent selected tuples are supplied for equivalent committed bars
- **THEN** dispatch order is the same

### Requirement: Per-unit dispatch failure is isolated
The orchestrator SHALL normalize one dispatch exception into a failed outcome and SHALL continue attempting remaining selected units.

#### Scenario: Dispatcher raises
- **WHEN** dispatch raises for one unit
- **THEN** the orchestrator records `strategy_cycle_dispatch_failed` for that unit
- **AND** continues with remaining selections

#### Scenario: Aggregate outcomes are returned
- **WHEN** every selected unit has been attempted
- **THEN** the result contains one outcome per selected deployment
- **AND** selected and attempted counts are equal
- **AND** succeeded plus failed counts equal attempted count

### Requirement: Dispatcher outcome identity is validated
The orchestrator SHALL fail closed when a dispatcher returns an outcome for a different strategy instance.

#### Scenario: Outcome identity differs
- **WHEN** dispatching identity `A` returns an outcome whose `strategy_instance_id` is `B`
- **THEN** the orchestrator substitutes a failed outcome for identity `A`
- **AND** uses error code `strategy_cycle_outcome_identity_mismatch`
- **AND** continues with remaining selections

### Requirement: Upstream preparation failure prevents fan-out
The orchestrator SHALL journal and wrap deployment-catalog or deployment-selection failure before dispatch.

#### Scenario: Deployment catalog fails
- **WHEN** catalog loading raises
- **THEN** the orchestrator records failure stage `deployment_catalog`
- **AND** raises `CommittedBarPreparationError` retaining that stage and cause
- **AND** dispatches no processing units

#### Scenario: Deployment selection fails
- **WHEN** deployment selection raises
- **THEN** the orchestrator records failure stage `deployment_selection`
- **AND** raises `CommittedBarPreparationError` retaining that stage and cause
- **AND** dispatches no processing units
