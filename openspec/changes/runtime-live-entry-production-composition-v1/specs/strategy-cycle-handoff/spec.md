## ADDED Requirements

### Requirement: Production composition attaches the semantic Runtime sink unconditionally
`strategy_runtime.bootstrap.application.build_application` SHALL always
attach a thin, `None`-returning sink function that calls the composed
`StrategyRuntimeOrchestrator.process(unit)` as
`StrategyCycleHandoffBoundary`'s production sink, replacing the previously
unattached (no-op) production default. `build_application` accepts no
caller-supplied sink parameter that could replace this production sink. The
boundary's own dispatch mechanics — attached/unattached sink behavior and
sink-exception propagation — are unchanged by this requirement, and the
boundary's existing general capability to be constructed directly with an
arbitrary sink (used by utility-level tests that do not go through
`build_application`) is unaffected.

#### Scenario: Default production sink is a thin wrapper over the semantic orchestrator
- **WHEN** `build_application` constructs a ready application
- **THEN** `StrategyCycleHandoffBoundary` is constructed with a thin,
  `None`-returning sink function that calls
  `StrategyRuntimeOrchestrator.process(unit)` and discards its result, for
  every dispatched unit
- **AND** the boundary is never left with an unattached (no-op) sink in any
  `ready=True` application
- **AND** `.dispatch` is not used as the sink (it would construct a second,
  discarded `StrategyCycleDispatchOutcome`)

#### Scenario: No new top-level orchestrator is introduced
- **WHEN** the production sink is attached
- **THEN** the attached sink is the existing `StrategyRuntimeOrchestrator`
- **AND** no additional top-level semantic or projection coordinator is
  introduced between `StrategyCycleHandoffBoundary` and
  `StrategyRuntimeOrchestrator`

#### Scenario: build_application accepts no composition override
- **WHEN** `build_application`'s public signature is inspected
- **THEN** it declares no parameter that lets a caller replace the production
  sink or otherwise substitute part of the composed graph
- **AND** utility-level tests that need a bare `StrategyCycleHandoffBoundary`
  with an arbitrary sink construct that boundary directly, not through
  `build_application`
