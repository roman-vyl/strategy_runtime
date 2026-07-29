## ADDED Requirements

### Requirement: Production composition attaches the semantic Runtime sink
`strategy_runtime.bootstrap.application.build_application` SHALL attach the
composed `StrategyRuntimeOrchestrator` as `StrategyCycleHandoffBoundary`'s
production sink by default, replacing the previously unattached (no-op)
production default. The boundary's own dispatch mechanics — attached/
unattached sink behavior and sink-exception propagation — are unchanged by
this requirement.

#### Scenario: Default production sink is the semantic orchestrator
- **WHEN** `build_application` constructs a ready application without a
  caller-supplied `strategy_cycle_handoff` override
- **THEN** `StrategyCycleHandoffBoundary` is constructed with a sink that
  invokes the composed `StrategyRuntimeOrchestrator` for every dispatched unit
- **AND** the boundary is not left with an unattached (no-op) sink in that
  default production path

#### Scenario: No new top-level orchestrator is introduced
- **WHEN** the production sink is attached
- **THEN** the attached sink is the existing `StrategyRuntimeOrchestrator`
- **AND** no additional top-level semantic or projection coordinator is
  introduced between `StrategyCycleHandoffBoundary` and
  `StrategyRuntimeOrchestrator`

#### Scenario: Test override seam remains available
- **WHEN** a caller supplies an explicit `strategy_cycle_handoff` argument to
  `build_application`
- **THEN** `StrategyCycleHandoffBoundary` uses that caller-supplied sink
  instead of the production `StrategyRuntimeOrchestrator` sink
- **AND** this remains a test-only override, not a documented production
  configuration path
