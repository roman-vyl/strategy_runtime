# strategy-cycle-handoff Specification

## Purpose
Define the terminal utility dispatch boundary that either accepts a prepared strategy/bar unit locally or forwards it unchanged to an attached downstream Runtime sink.

## Requirements
### Requirement: Utility exposes a terminal strategy-cycle handoff
Strategy Runtime SHALL provide `StrategyCycleHandoffBoundary` as a `StrategyCycleDispatchPort` implementation that accepts one immutable `StrategyBarProcessingUnit`.

#### Scenario: No downstream sink is attached
- **WHEN** the boundary dispatches a unit without an attached sink
- **THEN** it returns a successful outcome for the unit `strategy_instance_id`
- **AND** performs no semantic Runtime, Engine, ABI, position, or trading work

#### Scenario: Downstream sink is attached
- **WHEN** the boundary dispatches a unit with an attached sink
- **THEN** it passes the exact unit to the sink once
- **AND** returns a successful outcome for the same `strategy_instance_id`

### Requirement: Sink failures cross the handoff boundary
The handoff boundary SHALL allow a downstream sink exception to propagate to its orchestrator caller.

#### Scenario: Downstream sink raises
- **WHEN** the attached sink raises while accepting a unit
- **THEN** the boundary does not convert the exception into success
- **AND** `CommittedBarOrchestrator` remains responsible for per-unit failure normalization and isolation
