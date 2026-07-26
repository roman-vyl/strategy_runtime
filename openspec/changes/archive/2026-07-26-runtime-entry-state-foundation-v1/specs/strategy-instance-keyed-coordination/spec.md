## ADDED Requirements

### Requirement: Runtime provides process-local keyed strategy-instance coordination
Strategy Runtime SHALL provide a
`StrategyInstanceKeyedMutexRegistry` that supplies one process-local critical
section for an exact non-empty `strategy_instance_id`.

#### Scenario: Hold one instance critical section
- **WHEN** a caller enters `hold(strategy_instance_id)`
- **THEN** the caller owns the keyed critical section until the context exits
- **AND** the registry preserves the exact key without trimming, deriving, or normalizing it

#### Scenario: Reject an invalid coordination key
- **WHEN** the supplied key is empty or not a string
- **THEN** acquisition fails before any keyed lock is created or held

### Requirement: Same-instance critical sections are mutually exclusive
All callers using the same registry and exact `strategy_instance_id` SHALL
serialize on one keyed lock.

#### Scenario: Serialize two same-key callers
- **WHEN** one caller holds the critical section for an instance and another caller requests the same key
- **THEN** the second caller cannot enter until the first caller exits
- **AND** the two critical sections never overlap

#### Scenario: Atomically create one lock per key
- **WHEN** concurrent callers first request the same previously unseen key
- **THEN** the registry creates or selects one shared keyed lock
- **AND** no caller enters through a separate lock for that key

### Requirement: Different strategy instances can proceed independently
The keyed registry SHALL NOT serialize callers solely because they use the same
registry when their strategy-instance keys differ.

#### Scenario: Overlap different-key critical sections
- **WHEN** callers request two different valid strategy-instance IDs
- **THEN** both callers can hold their respective critical sections concurrently
- **AND** waiting on one instance does not block acquisition for the other instance

### Requirement: Context exit always releases the keyed lock
The keyed coordination boundary SHALL release its instance lock when the
context exits normally or because an exception propagates.

#### Scenario: Release after normal completion
- **WHEN** a caller leaves the keyed context normally
- **THEN** a later same-key caller can enter

#### Scenario: Release after failure
- **WHEN** code inside the keyed context raises an exception
- **THEN** the original exception can propagate
- **AND** the keyed lock is released
- **AND** a later same-key caller can enter

### Requirement: Keyed coordination remains independent of state behavior
The registry SHALL provide only mutual exclusion and SHALL NOT perform Runtime
state, reconciliation, transport, or orchestration work.

#### Scenario: Keep application behavior outside the registry
- **WHEN** a keyed critical section is created, entered, or exited
- **THEN** the registry does not call the repository, Strategy Engine, ABI, or an HTTP handler
- **AND** it does not create a trade cycle, apply a package, or decide when a future writer acquires the lock

#### Scenario: Share one registry across later writers
- **WHEN** later Runtime state writers receive the same registry instance and request the same strategy-instance key
- **THEN** both critical sections are backed by the same keyed lock

### Requirement: Live V1 coordination makes no cross-process guarantee
`StrategyInstanceKeyedMutexRegistry` SHALL provide only in-process
serialization and SHALL NOT claim multi-worker, multi-replica, or restart
durability.

#### Scenario: Distinguish the repository lock
- **WHEN** the in-memory repository protects one dictionary operation with its internal lock
- **THEN** that lock does not replace the keyed application critical section

#### Scenario: Defer stronger coordination
- **WHEN** Live V1 runs with more than one process or replica
- **THEN** this capability alone does not serialize those processes
- **AND** distributed locking, repository CAS, and durable pending actions remain outside I2
