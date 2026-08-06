## ADDED Requirements

### Requirement: Runtime freezes first-fill context before routing an open position
Between position resolution and routing, when `resolved.position_open` is
`true`, `StrategyRuntimeOrchestrator.process(...)` SHALL call the existing
`apply_first_fill` transition with the current trade cycle's
`trade_cycle_id` and `resolved.first_fill_at_ms`, save a resulting changed
state through the repository before routing, and pass the (possibly
updated) resolved state into `StrategyUseCaseRouter`. This runs inside the
same keyed critical section already held for `process(...)`.

#### Scenario: Freeze and save before routing
- **WHEN** `resolved.position_open` is `true` and the current trade cycle's
  `frozen_entry_context` is still null
- **THEN** `apply_first_fill` returns a new state with a frozen context
- **AND** the orchestrator saves that state through the repository before
  calling `StrategyUseCaseRouter.route(...)`
- **AND** the router receives the saved, frozen state

#### Scenario: Already-frozen context is a no-op
- **WHEN** `resolved.position_open` is `true` and the current trade cycle
  already carries a `frozen_entry_context` matching
  `resolved.first_fill_at_ms`
- **THEN** `apply_first_fill` returns the identical input state object
- **AND** the orchestrator does not call repository `save(...)`
- **AND** routing proceeds with the unchanged resolved state

#### Scenario: A conflicting fill timestamp fails closed before routing
- **WHEN** `resolved.position_open` is `true` and `resolved.first_fill_at_ms`
  differs from an already-frozen context's `first_fill_at_ms` for the same
  trade cycle
- **THEN** `apply_first_fill` raises `FirstFillInvariantError`
- **AND** that error propagates out of `process(...)`
- **AND** the router is not called and no save occurs

#### Scenario: A closed position skips the freeze step entirely
- **WHEN** `resolved.position_open` is `false`
- **THEN** the orchestrator does not call `apply_first_fill`
- **AND** routing proceeds exactly as before this change

#### Scenario: The freeze save is not undone by a later failure
- **WHEN** the freeze-and-save step completes and a subsequent router or
  Engine call raises
- **THEN** the already-saved frozen first-fill context is not reverted,
  re-fetched, or superseded by that failure
- **AND** `process(...)` still lets the later exception propagate

#### Scenario: Serialize against the ABI first-fill callback
- **WHEN** `AbiExecutionEventOrchestrator` and the closed-bar path both
  reach `apply_first_fill` for the same strategy instance
- **THEN** the shared keyed mutex forces them to run sequentially, not
  concurrently
- **AND** whichever runs second observes the first's frozen context as
  already set, producing a no-op for an identical timestamp or a fail-closed
  raise for a conflicting one
