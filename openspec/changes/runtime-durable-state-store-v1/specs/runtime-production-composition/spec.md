## MODIFIED Requirements

### Requirement: Non-durable Live V1 limitation is accepted, not open
Strategy Runtime SHALL use exactly one bounded, in-memory, non-persisted
committed-bar intake queue in the production graph, and SHALL treat the
resulting non-durable behavior of that queue as an accepted Live V1
limitation. Strategy-instance state is no longer part of this accepted
limitation: the production graph SHALL use exactly one
`JsonlStrategyInstanceRuntimeStateRepository` (see
`runtime-durable-state-store`) as the shared state repository, not
`InMemoryStrategyInstanceRuntimeStateRepository`.

#### Scenario: Durable file-backed repository is the selected implementation
- **WHEN** the production graph is constructed
- **THEN** the shared state repository is
  `JsonlStrategyInstanceRuntimeStateRepository`
- **AND** `InMemoryStrategyInstanceRuntimeStateRepository` is not composed
  for production — only for tests and other explicitly ephemeral
  compositions

#### Scenario: A lost in-flight cycle remains an accepted queue-level risk
- **WHEN** Runtime terminates after acknowledging a webhook but before
  its queued committed-bar cycle completes, whether or not the worker
  had already dequeued it from the intake queue
- **THEN** that event is lost with no persisted pending action, replay,
  or recovery mechanism, and this remains an accepted Live V1 limitation
  of the committed-bar intake queue
- **AND** this loss is independent of strategy-instance state durability —
  a strategy instance's already-saved state still survives that same
  restart

## ADDED Requirements

### Requirement: Durable state replay gates ready composition fail-closed
`build_application` SHALL replay `RUNTIME_STATE_PATH` through
`JsonlStrategyInstanceRuntimeStateRepository` during startup, before
reporting `ready=True`, and SHALL report `ready=False` when that path
cannot be prepared or when replay detects a fail-closed integrity
violation (a corrupted record other than a tolerated truncated final
line, per `runtime-durable-state-store`).

#### Scenario: Successful replay is part of reaching ready
- **WHEN** `RUNTIME_STATE_PATH` is a valid, writable path and its file (if
  present) contains only valid records, or a tolerated truncated final
  line
- **THEN** `build_application` completes replay and, together with every
  other required component, reports `ready=True`

#### Scenario: A replay integrity failure fails closed
- **WHEN** replay detects a corrupted record other than a tolerated
  truncated final line
- **THEN** `build_application` does not construct a `ready=True`
  application
- **AND** no partially recovered state repository is exposed to
  `StrategyRuntimeOrchestrator` or `AbiExecutionEventOrchestrator`

#### Scenario: An unusable state path fails closed
- **WHEN** `RUNTIME_STATE_PATH` cannot be created, is not a file, or is not
  writable
- **THEN** `build_application` reports `ready=False`, consistent with the
  existing fail-closed gate already applied to every other required
  component
