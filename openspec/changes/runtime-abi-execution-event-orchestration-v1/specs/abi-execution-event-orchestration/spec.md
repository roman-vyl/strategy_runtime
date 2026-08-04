## ADDED Requirements

### Requirement: AbiExecutionEventOrchestrator is the top-level sequencing boundary for an ABI first-fill execution event
Strategy Runtime SHALL provide `AbiExecutionEventOrchestrator.process(event:
AbiFirstFillExecutionEvent) -> StrategyInstanceRuntimeState` as a second,
independent top-level writer path alongside `StrategyRuntimeOrchestrator`,
containing only mutex acquisition, state load, one call to the existing
`apply_first_fill` domain transition, and conditional save — no other
application logic.

#### Scenario: Process one ABI first-fill event end to end
- **WHEN** `process(event)` is called with a valid
  `AbiFirstFillExecutionEvent` for a registered `strategy_instance_id`
  carrying a matching `current_trade_cycle`
- **THEN** the orchestrator acquires the keyed mutex, loads the current
  aggregate, calls `apply_first_fill` exactly once, conditionally saves, and
  returns the final `StrategyInstanceRuntimeState`

#### Scenario: The orchestrator introduces no sequencing step beyond mutex, load, transition, and conditional save
- **WHEN** `process(...)` executes
- **THEN** it performs no step other than acquiring the keyed critical
  section, calling `StrategyInstanceRuntimeStateRepository.get(...)`,
  calling `apply_first_fill`, and conditionally calling
  `StrategyInstanceRuntimeStateRepository.save(...)`

### Requirement: The orchestrator's input carries the unnormalized fill timestamp under the name apply_first_fill already uses
`AbiFirstFillExecutionEvent` SHALL carry exactly `strategy_instance_id: str`,
`trade_cycle_id: str`, and `first_fill_at_ms: int`, matching the parameter
name already used by `apply_first_fill` and by
`OpenPositionLookupResponse.first_fill_at_ms`, and SHALL NOT carry
`entry_bar_open_time_ms` or any other Engine-facing normalized-timestamp
field.

#### Scenario: Input never exposes the Engine-facing canonical field name
- **WHEN** `AbiFirstFillExecutionEvent` is constructed
- **THEN** it has no field named `entry_bar_open_time_ms`
- **AND** its timestamp field is named `first_fill_at_ms`, carrying the
  unnormalized millisecond value exactly as supplied

#### Scenario: Input carries no execution-phase or quantity data
- **WHEN** `AbiFirstFillExecutionEvent` is constructed
- **THEN** it carries no execution `phase`, filled or remaining quantity,
  average execution price, or fill ledger

### Requirement: The orchestrator acquires the shared keyed mutex by exact strategy_instance_id before loading any state
`AbiExecutionEventOrchestrator` SHALL enter
`StrategyInstanceKeyedMutexRegistry.hold(event.strategy_instance_id)` before
calling `StrategyInstanceRuntimeStateRepository.get(...)`, using the exact
supplied `strategy_instance_id` with no trimming, deriving, or normalizing.

#### Scenario: Mutex acquired before state load
- **WHEN** `process(event)` starts
- **THEN** it enters `hold(event.strategy_instance_id)` before any
  repository call
- **AND** no repository call occurs before the keyed critical section is
  held

#### Scenario: Mutex is keyed on the exact supplied strategy_instance_id
- **WHEN** two calls to `process(...)` supply the exact same
  `strategy_instance_id` string
- **THEN** both acquire the same keyed critical section
- **AND** no derived or normalized key is used to acquire the lock

### Requirement: The orchestrator loads fresh state through get, never get_or_create, and fails closed when no aggregate is registered
`AbiExecutionEventOrchestrator` SHALL call
`StrategyInstanceRuntimeStateRepository.get(event.strategy_instance_id)`
exactly once per invocation, SHALL NOT call `get_or_create(...)`, and SHALL
raise a typed missing-state error without calling `apply_first_fill` or
`save(...)` when `get(...)` returns `None`.

#### Scenario: Load through get, not get_or_create
- **WHEN** `process(event)` loads state
- **THEN** it calls `StrategyInstanceRuntimeStateRepository.get(...)`
  exactly once
- **AND** it never calls `get_or_create(...)`

#### Scenario: Fail closed when the aggregate is not registered
- **WHEN** `get(event.strategy_instance_id)` returns `None`
- **THEN** `process(...)` raises `StrategyInstanceStateNotFound`
- **AND** `apply_first_fill` is not called
- **AND** `save(...)` is not called
- **AND** no aggregate is created or registered as a side effect

#### Scenario: Never synthesize a bare aggregate to proceed
- **WHEN** no aggregate is registered for the supplied `strategy_instance_id`
- **THEN** the orchestrator does not construct or persist any
  `StrategyInstanceRuntimeState` to make `apply_first_fill` callable
- **AND** the operation ends with the missing-state error, not a
  partially-formed state

### Requirement: The orchestrator delegates timestamp normalization and freezing entirely to the existing apply_first_fill transition
`AbiExecutionEventOrchestrator` SHALL call `apply_first_fill(state,
event.trade_cycle_id, event.first_fill_at_ms)` exactly once per invocation
after a successful load, and SHALL NOT perform candle-grid alignment,
timeframe lookup, entry-context construction, or any other domain
computation itself.

#### Scenario: Call apply_first_fill with the loaded state and event fields unchanged
- **WHEN** `process(event)` has a loaded aggregate
- **THEN** it calls `apply_first_fill(state, event.trade_cycle_id,
  event.first_fill_at_ms)` exactly once
- **AND** passes the loaded aggregate and the event's fields unmodified

#### Scenario: No normalization logic duplicated in the orchestrator
- **WHEN** `process(...)` runs
- **THEN** it does not call `align_first_fill_to_entry_bar` directly
- **AND** it does not construct a `FrozenExecutedEntryContext` itself
- **AND** it does not read or branch on `registered_spec_snapshot.
  base_timeframe`

### Requirement: The orchestrator saves only when apply_first_fill returns a distinct state object
`AbiExecutionEventOrchestrator` SHALL compare the result of
`apply_first_fill` to the loaded state using object identity
(`resulting_state is state`), matching `apply_first_fill`'s own documented
no-op contract, and SHALL call `save(...)` exactly once only when the
result is a different object.

#### Scenario: Identical retry performs no save
- **WHEN** `apply_first_fill` returns the identical `state` object reference
  it was given
- **THEN** `process(...)` does not call `save(...)`
- **AND** returns that same state object

#### Scenario: A confirmed freeze saves exactly once
- **WHEN** `apply_first_fill` returns a new, distinct
  `StrategyInstanceRuntimeState` object
- **THEN** `process(...)` calls `save(...)` exactly once with that object
- **AND** returns the exact object returned by `save(...)`, not the
  pre-save input

### Requirement: The orchestrator holds the keyed mutex across the complete load-transition-save sequence and always releases it
`AbiExecutionEventOrchestrator` SHALL hold the keyed critical section from
before `get(...)` through the conditional `save(...)`, and SHALL release it
whether `process(...)` completes successfully or an exception propagates
from any stage.

#### Scenario: Hold through the full sequence
- **WHEN** `process(event)` progresses through load, `apply_first_fill`, and
  conditional save
- **THEN** the same keyed critical section remains held for the entire
  sequence
- **AND** it is not released and reacquired between stages

#### Scenario: Release after successful completion
- **WHEN** `process(...)` returns successfully, with or without a save
- **THEN** the keyed critical section is released
- **AND** a later same-instance caller can acquire it

#### Scenario: Release after any exception
- **WHEN** `get(...)`, `apply_first_fill`, or `save(...)` raises an
  exception
- **THEN** the original exception propagates
- **AND** the keyed critical section is released
- **AND** a later same-instance caller can acquire it

### Requirement: The orchestrator calls no Engine, ABI outbound, or sibling-orchestrator collaborator
`AbiExecutionEventOrchestrator` SHALL NOT call Strategy Engine, any ABI
outbound client, `StrategyRuntimeOrchestrator`, or
`EntryReconciliationOrchestrator`, and SHALL NOT construct any Strategy
Engine request or response DTO.

#### Scenario: No Engine or ABI call is made
- **WHEN** `process(...)` executes, whether it saves or not
- **THEN** no Strategy Engine port is called
- **AND** no ABI outbound client is called

#### Scenario: No sibling orchestrator is invoked
- **WHEN** `process(...)` executes
- **THEN** `StrategyRuntimeOrchestrator` is not called
- **AND** `EntryReconciliationOrchestrator` is not called

### Requirement: Domain and repository exceptions propagate unmasked
`AbiExecutionEventOrchestrator` SHALL let every exception raised by
`apply_first_fill` or by the repository propagate without translation,
suppression, retry, or fallback.

#### Scenario: A domain invariant failure propagates and performs no save
- **WHEN** `apply_first_fill` raises `FirstFillInvariantError` or the
  `ValueError` it lets propagate unwrapped from `align_first_fill_to_entry_
  bar`
- **THEN** that exact exception propagates from `process(...)`
- **AND** `save(...)` is not called

#### Scenario: A repository save failure propagates
- **WHEN** `save(...)` raises for a value-different replacement
- **THEN** that exception propagates after exactly one save attempt
- **AND** `process(...)` performs no retry, compensating write, or
  successful return

### Requirement: AbiExecutionEventOrchestrator and StrategyRuntimeOrchestrator are equal writer paths sharing one repository and one keyed-mutex registry
A conforming production wiring SHALL construct exactly one
`StrategyInstanceRuntimeStateRepository` instance and exactly one
`StrategyInstanceKeyedMutexRegistry` instance and supply both to
`AbiExecutionEventOrchestrator` and to `StrategyRuntimeOrchestrator`, so
that the two top-level writer paths serialize per exact
`strategy_instance_id` and observe each other's saved state.

#### Scenario: Same-instance invocations across both writers serialize
- **WHEN** `StrategyRuntimeOrchestrator.process(...)` and
  `AbiExecutionEventOrchestrator.process(...)` are invoked for the same
  exact `strategy_instance_id` against the shared registry
- **THEN** their critical sections do not overlap
- **AND** whichever invocation acquires the mutex second loads state only
  after the first invocation releases it

#### Scenario: A fresh load observes the other writer's prior save
- **WHEN** `StrategyRuntimeOrchestrator` saves a replacement aggregate for
  an instance and then releases the mutex
- **AND** `AbiExecutionEventOrchestrator.process(...)` is subsequently
  invoked for the same `strategy_instance_id` against the shared repository
  and registry
- **THEN** its `get(...)` call returns the aggregate `StrategyRuntimeOrchestrator`
  saved, not an earlier snapshot

#### Scenario: Different strategy instances remain independent across both writers
- **WHEN** `StrategyRuntimeOrchestrator` holds its critical section for one
  `strategy_instance_id` and `AbiExecutionEventOrchestrator.process(...)`
  is invoked for a different `strategy_instance_id` against the same shared
  registry
- **THEN** the second invocation acquires its own critical section without
  waiting on the first
