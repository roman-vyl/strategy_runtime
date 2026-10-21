## Purpose

Define the minimal durable marker Runtime writes before issuing a
Runtime-decided `ClosePosition` execution, so a lost or ambiguous response to
that specific mutation can later be resolved against ABI's pair-scoped truth
instead of leaving `current_trade_cycle` permanently frozen.

## ADDED Requirements

### Requirement: Strategy-instance state owns at most one minimal pending close-recovery marker
`StrategyInstanceRuntimeState` SHALL own an optional `pending_close_recovery:
PendingCloseRecovery | None` field, a sibling of `current_trade_cycle` and of
`pending_entry_recovery`, not a variant of either. A null value means no
`ClosePosition` mutation issued by this Runtime process is currently
uncertain for this instance.

#### Scenario: Field exists as its own sibling
- **WHEN** `StrategyInstanceRuntimeState` is defined
- **THEN** it exposes `pending_close_recovery` as a field distinct from
  `current_trade_cycle` and `pending_entry_recovery`
- **AND** no existing field is reused or overloaded to represent this marker

#### Scenario: Null means no uncertain close mutation
- **WHEN** `pending_close_recovery` is null
- **THEN** no `ClosePosition` command issued by this Runtime process is
  currently unresolved for this instance

### Requirement: PendingCloseRecovery has only the one field needed to ask ABI which trade cycle is uncertain
`PendingCloseRecovery` SHALL contain exactly one non-empty field,
`trade_cycle_id: str`. It SHALL NOT contain an action-kind discriminator (this
marker only ever means "close"), a desired-entry or desired-protection value,
a timestamp, a retry counter, a command identifier, or any other field. No
wall-clock recovery horizon is derived from or stored alongside this marker.

#### Scenario: Exactly one field
- **WHEN** `PendingCloseRecovery` is constructed
- **THEN** it holds exactly `trade_cycle_id: str` and no other field

#### Scenario: Reject construction with an empty identity
- **WHEN** `PendingCloseRecovery` is constructed with an empty
  `trade_cycle_id`
- **THEN** construction fails before the value can be used

### Requirement: The marker's trade_cycle_id always identifies the same cycle current_trade_cycle already holds
Because a Runtime-issued `ClosePosition` command only ever targets the
instance's own already-acknowledged `current_trade_cycle`, `current_trade_cycle`
SHALL be non-null whenever `pending_close_recovery` is non-null, and
`pending_close_recovery.trade_cycle_id` SHALL always equal
`current_trade_cycle.trade_cycle_id`. Unlike `pending_entry_recovery`, this
marker has no "uncertain create" counterpart where `current_trade_cycle` is
null — closing an absent cycle is not a Runtime-issued mutation this
capability models.

#### Scenario: A non-null close marker always accompanies a non-null current cycle
- **WHEN** `pending_close_recovery` is non-null
- **THEN** `current_trade_cycle` is non-null
- **AND** `pending_close_recovery.trade_cycle_id` equals
  `current_trade_cycle.trade_cycle_id`

#### Scenario: No uncertain-create analog exists for close
- **WHEN** `current_trade_cycle` is null
- **THEN** `pending_close_recovery` is also null — there is no scenario where
  a close marker exists without the cycle it targets

### Requirement: A non-null pending close marker does not itself prove any exchange state
The presence of a non-null `pending_close_recovery` SHALL NOT be treated as
proof that the exchange position is closed, still open, or in any other
particular state. It records only that this Runtime process issued a
`ClosePosition` command whose outcome it has not yet durably confirmed.

#### Scenario: Marker presence is not exchange truth
- **WHEN** `pending_close_recovery` is non-null
- **THEN** no component infers from that fact alone whether the exchange
  position is open or closed
- **AND** only a later ABI-sourced confirmation or resolver outcome may
  establish that fact

### Requirement: pending_entry_recovery and pending_close_recovery are mutually exclusive
At most one of `pending_entry_recovery` and `pending_close_recovery` SHALL be
non-null on any `StrategyInstanceRuntimeState` at a time. This is enforced at
construction (and therefore at decode, since decoding reconstructs the
aggregate through its normal constructor) — it is not left to incidental
ordering in any caller such as the resolver's own `if`/`elif` dispatch.
Normal Runtime flow never needs both non-null simultaneously:
`StrategyRuntimeOrchestrator.process()`'s pending-recovery guard already
defers the entire pipeline — including `EntryReconciliationOrchestrator` and
`PositionManagementOrchestrator` — whenever either marker is already
non-null, so neither orchestrator's pre-write can ever run while the other
marker is set.

#### Scenario: Construction rejects both markers set together
- **WHEN** `StrategyInstanceRuntimeState` is constructed with both
  `pending_entry_recovery` and `pending_close_recovery` non-null
- **THEN** construction fails before the value can be used

#### Scenario: A schema_version 3 durable line with both markers non-null fails closed on decode
- **WHEN** a `schema_version = 3` durable line holds a non-null
  `pending_entry_recovery` and a non-null `pending_close_recovery`
- **THEN** decoding raises a schema/domain validation failure through the
  same construction path, and replay treats it exactly like any other
  fail-closed record

#### Scenario: Existing schema_version 1/2 decoding is unaffected
- **WHEN** a `schema_version = 1` line (no markers) or a `schema_version = 2`
  line (only `pending_entry_recovery`, no `pending_close_recovery` key)
  decodes
- **THEN** decoding succeeds exactly as it did before this invariant existed
  — a `schema_version = 1` or `2` line can never carry both keys, so this
  invariant never rejects one

#### Scenario: One marker set, or both null, decodes and constructs normally
- **WHEN** exactly one of `pending_entry_recovery`/`pending_close_recovery`
  is non-null, or both are null
- **THEN** construction and decoding succeed normally

### Requirement: No file rewrite is required to introduce this field
Introducing `pending_close_recovery` SHALL follow the same additive,
non-rewriting migration shape `runtime-durable-state-store` already
established for `pending_entry_recovery`'s `schema_version` 1→2 introduction:
a new `schema_version` value makes the field a required (nullable) envelope
key going forward, and no existing durable line is rewritten, migrated, or
compacted.

#### Scenario: Existing durable lines remain valid without rewrite
- **WHEN** the durable file contains lines written before this field existed
- **THEN** those lines continue to decode successfully, with
  `pending_close_recovery` treated as absent-and-null for that schema version
- **AND** no migration or rewrite step touches those lines
