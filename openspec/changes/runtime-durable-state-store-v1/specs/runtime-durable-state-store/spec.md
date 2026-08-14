## ADDED Requirements

### Requirement: Strategy-instance state is stored in one shared append-only JSONL file
`JsonlStrategyInstanceRuntimeStateRepository` SHALL persist every
`StrategyInstanceRuntimeState` as one complete JSON line appended to one
shared file at a configured path, keyed by `strategy_instance_id`, where the
latest valid line for a key is that key's current durable state.

#### Scenario: One line per save, one file for every instance
- **WHEN** the repository creates or replaces state for any
  `strategy_instance_id`
- **THEN** it appends exactly one complete JSON line to the one configured
  file
- **AND** no separate file or directory is created per strategy instance

#### Scenario: Later valid record for a key supersedes an earlier one
- **WHEN** the file contains more than one valid line for the same
  `strategy_instance_id`
- **THEN** the line appearing later in the file is that key's current state
- **AND** earlier lines for that key are superseded, not merged

#### Scenario: A line is a complete snapshot, never a diff
- **WHEN** the repository appends a line
- **THEN** that line contains the complete aggregate exactly as
  `save()`/`get_or_create()` received or produced it
- **AND** no partial-field or diff/patch line is ever written

### Requirement: A successful save is already physically durable
`JsonlStrategyInstanceRuntimeStateRepository.save(...)` (and the creation
path of `get_or_create(...)`) SHALL NOT return successfully until the
serialized record has been appended, flushed, and `fsync`'d to the
underlying file.

#### Scenario: Save completes only after fsync
- **WHEN** `save(...)` is called with a valid aggregate
- **THEN** the repository serializes the aggregate, appends it, flushes the
  write buffer, and calls `fsync` on the file descriptor before returning
  the stored aggregate
- **AND** no step of that sequence is deferred to a background thread or
  batched with another call

#### Scenario: A failure during the durability sequence does not update in-memory state
- **WHEN** serialization, the append write, the flush, or the `fsync` call
  raises
- **THEN** `save(...)` propagates the exception
- **AND** the repository's in-memory index for that `strategy_instance_id`
  is not updated to the failed value

### Requirement: Physical appends are serialized independently of business-level coordination
`JsonlStrategyInstanceRuntimeStateRepository` SHALL serialize its physical
append operations, across every `strategy_instance_id`, through its own
internal lock, distinct from `StrategyInstanceKeyedMutexRegistry`.

#### Scenario: Two different instances' appends never interleave mid-line
- **WHEN** saves for two different `strategy_instance_id` values are
  physically appended around the same time
- **THEN** each append's line is written as one complete, non-interleaved
  write
- **AND** the file never contains a line formed from two different saves

#### Scenario: The repository lock does not replace keyed business coordination
- **WHEN** a caller has not acquired
  `StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)` before
  calling `save(...)`
- **THEN** the repository's internal append lock alone does not decide
  whether that caller held the correct business-level critical section —
  that responsibility remains the caller's, unchanged from the existing
  `strategy-instance-runtime-state-repository` contract

### Requirement: Startup replay recovers the latest valid snapshot per strategy instance
`JsonlStrategyInstanceRuntimeStateRepository` SHALL, at construction, replay
its configured file and populate its in-memory index with the latest valid
record for every `strategy_instance_id` found, before the repository serves
any `get_or_create`, `get`, or `save` call.

#### Scenario: Replay restores prior state without external reconstruction
- **WHEN** the repository is constructed against a file containing valid
  prior records
- **THEN** `get(strategy_instance_id)` for a previously saved instance
  returns that instance's latest saved aggregate immediately after
  construction, with no call to ABI, Strategy Engine, or the exchange
  during replay

#### Scenario: Replay of an empty or absent file yields no state
- **WHEN** the configured file is empty or does not yet exist
- **THEN** replay completes with an empty in-memory index
- **AND** no error is raised solely because no prior records exist

### Requirement: Replay fails closed on corrupted state, except a syntactically truncated final line
Replay SHALL validate every line's JSON syntax and, for syntactically valid
lines, SHALL validate the record against `StrategyInstanceRuntimeState`'s
full envelope/schema/domain validation. A line other than the file's last
line that fails to parse as JSON SHALL abort replay with a fail-closed
error. The file's last line, and only the last line, MAY fail to parse as
JSON and still be tolerated — as a truncated write left by a crash
mid-append — by discarding it and keeping the prior valid record for that
key, if any. A line that parses as syntactically valid JSON but fails
envelope/schema/domain validation SHALL always abort replay with a
fail-closed error, regardless of its position in the file — including the
last line; syntactic validity does not earn leniency for domain-invalid
content.

#### Scenario: A JSON parse failure before the last line fails closed
- **WHEN** a line other than the last line cannot be parsed as JSON
- **THEN** replay raises a fail-closed error
- **AND** the repository does not become ready to serve requests

#### Scenario: A syntactically truncated last line is discarded, not fatal
- **WHEN** the file's last line cannot be parsed as JSON, and every prior
  line replayed successfully
- **THEN** replay discards that last line
- **AND** the affected key's state is whatever its last valid prior record
  was — null if it had none
- **AND** replay otherwise completes successfully

#### Scenario: A schema/domain validation failure fails closed regardless of position
- **WHEN** any line, including the last line, parses as syntactically valid
  JSON but does not satisfy `StrategyInstanceRuntimeState` envelope/schema
  or domain validation — a missing required field, wrong type, or invalid
  decimal text
- **THEN** replay raises a fail-closed error
- **AND** the repository does not become ready to serve requests — this
  holds even when the failing line is the file's last line

#### Scenario: A fully valid last line is applied normally
- **WHEN** the file's last line parses and validates successfully
- **THEN** it is applied exactly like any other valid record, with no
  special-cased leniency

### Requirement: The durable state store is independent of the processing journal
`JsonlStrategyInstanceRuntimeStateRepository` SHALL use a file, code path,
and correctness semantics entirely separate from `processing_journal`, and
strategy-instance state recovery SHALL NOT read the processing journal.

#### Scenario: Distinct files and distinct guarantees
- **WHEN** both the durable state store and the processing journal are
  configured
- **THEN** they write to two different configured paths
- **AND** a processing-journal write failure (silently absorbed, per
  `processing-journal`'s best-effort requirement) has no effect on whether
  a state `save()` is considered durable

#### Scenario: State recovery never falls back to journal content
- **WHEN** the durable state file is replayed at startup
- **THEN** no processing-journal event is read, parsed, or used to
  reconstruct any part of `StrategyInstanceRuntimeState`

### Requirement: V1 is a single-process, non-compacting store
`JsonlStrategyInstanceRuntimeStateRepository` SHALL be designed for exactly
one writing Runtime process, SHALL grow its file only by appending, and
SHALL provide no compaction, rotation, retention, or distributed
coordination (no compare-and-swap, no distributed lock, no leader
election).

#### Scenario: No compaction is performed
- **WHEN** the file accumulates superseded records for the same
  `strategy_instance_id` over time
- **THEN** the repository does not rewrite, truncate, or compact the file
  to remove superseded records

#### Scenario: No cross-process coordination is claimed
- **WHEN** more than one process opens the same configured file for
  writing
- **THEN** the repository provides no detection of, or protection against,
  that condition — this remains a documented single-process-writer
  deployment constraint, not a capability of the store itself

### Requirement: Decoding enforces the exact key set of every persisted structure except `raw_spec`
Decoding a durable JSONL line SHALL reject, as a schema/domain validation
failure, any field not in the exact allowed set for the envelope,
`CurrentTradeCycle`, `AppliedEntryPackage`, `DesiredEntry`,
`FrozenExecutedEntryContext`, and `DesiredProtection`, and SHALL equally
reject any of those structures' fields being absent — including a
nullable field such as `current_trade_cycle`, `frozen_entry_context`,
`latest_confirmed_management_protection`, or
`DesiredProtection.take_price`. A record is a complete snapshot: a
nullable field MUST still be present with an explicit JSON `null`;
omitting the key is a schema violation, not an implicit null, and decoding
SHALL NOT treat a missing key the same as a present key holding `null`.
`raw_spec` SHALL remain exempt from both checks: its own internal keys are
never restricted or required, only the presence of the `raw_spec` field
itself within `registered_spec_snapshot`.

#### Scenario: An unrecognized top-level envelope field fails closed
- **WHEN** a line's envelope contains a field outside
  `schema_version`, `strategy_instance_id`, `strategy_id`,
  `registered_spec_snapshot`, `risk_multiplier`, and `current_trade_cycle`
- **THEN** decoding raises a schema/domain validation failure
- **AND** replay applies this exactly like any other such failure — fail
  closed on any line, and fail closed even when confined to the last line

#### Scenario: An unrecognized field inside a nested structure fails closed
- **WHEN** `current_trade_cycle`, `applied_entry_package`,
  `desired_entry`, `frozen_entry_context`, or
  `latest_confirmed_management_protection` contains a field outside that
  structure's exact allowed set
- **THEN** decoding raises a schema/domain validation failure, with the
  same fail-closed replay handling as any other invalid record

#### Scenario: A missing nullable field fails closed instead of decoding as null
- **WHEN** a persisted structure omits a key that its schema defines as
  nullable — `current_trade_cycle` on the envelope,
  `frozen_entry_context` or `latest_confirmed_management_protection` on
  `CurrentTradeCycle`, or `take_price` on
  `latest_confirmed_management_protection` — rather than including that
  key with a JSON `null` value
- **THEN** decoding raises a schema/domain validation failure
- **AND** it does not silently substitute `None` for the missing key

#### Scenario: An explicit JSON null for a nullable field decodes normally
- **WHEN** a persisted structure includes a nullable field's key with an
  explicit JSON `null` value
- **THEN** decoding succeeds and that field decodes to `None`, exactly as
  if the field had never held a value

#### Scenario: Fields inside `raw_spec` are never restricted or required
- **WHEN** `registered_spec_snapshot.raw_spec` contains any JSON-object
  keys, including ones this repository has never seen before, or omits
  keys another `raw_spec` happened to have
- **THEN** decoding does not reject the record on that basis — `raw_spec`
  is opaque deployment content, not a structure this store defines

### Requirement: A physical write failure poisons the repository
Once `JsonlStrategyInstanceRuntimeStateRepository`'s physical append step
(open, write, flush, `fsync`) fails, the repository SHALL treat every
subsequent `get_or_create`, `get`, and `save` call on that instance as a
fail-closed error for the remainder of the process, instead of continuing
to serve from its last known in-memory state. A failure before the
physical write is attempted (serialization) SHALL NOT poison the
repository.

#### Scenario: A physical write failure poisons the instance
- **WHEN** the open/write/flush/`fsync` sequence inside `_append` raises
  for any reason
- **THEN** the triggering call's exception propagates to its caller
  unchanged
- **AND** every later `get_or_create`, `get`, or `save` call on that same
  repository instance raises a typed poisoned-store error instead of
  reading or mutating the in-memory index or attempting another physical
  write

#### Scenario: Poisoning is instance-wide, not per-key
- **WHEN** a physical write failure occurs while appending state for one
  `strategy_instance_id`
- **THEN** a later call for any other `strategy_instance_id` on that same
  repository instance also fails closed with the poisoned-store error

#### Scenario: A pre-physical-write failure does not poison
- **WHEN** serialization fails before the physical write is attempted
- **THEN** the repository is not poisoned
- **AND** subsequent calls continue to serve normally, exactly as before
  this requirement existed

#### Scenario: Recovery is a process restart, not an unpoison operation
- **WHEN** a repository instance is poisoned
- **THEN** no method call on that instance clears the poison
- **AND** a fresh `JsonlStrategyInstanceRuntimeStateRepository` constructed
  against the same path (as happens on process restart) replays the file
  from scratch and is not poisoned by a prior instance's poison state
