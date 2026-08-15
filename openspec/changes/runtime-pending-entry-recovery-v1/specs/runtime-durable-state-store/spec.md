## MODIFIED Requirements

### Requirement: Decoding enforces the exact key set of every persisted structure except `raw_spec`
Decoding a durable JSONL line SHALL reject, as a schema/domain validation
failure, any field not in the exact allowed set for the envelope,
`RegisteredSpecSnapshot`, `CurrentTradeCycle`, `AppliedEntryPackage`,
`DesiredEntry`, `FrozenExecutedEntryContext`, `DesiredProtection`, and
`PendingEntryRecovery`, and SHALL equally reject any of those structures'
fields being absent — including a nullable field such as `current_trade_cycle`,
`frozen_entry_context`, `latest_confirmed_management_protection`,
`DesiredProtection.take_price`, or (for a `schema_version = 2` line)
`pending_entry_recovery`. A record is a complete snapshot: a nullable field
MUST still be present with an explicit JSON `null`; omitting the key is a
schema violation, not an implicit null, and decoding SHALL NOT treat a
missing key the same as a present key holding `null`. The envelope's exact
allowed key set is itself version-dependent (see "Decoding dispatches by
`schema_version`, supporting exactly versions 1 and 2"): a `schema_version =
1` envelope's allowed set has no `pending_entry_recovery` key at all, and its
absence there is not a violation of this requirement — it is the
version-specific rule that governs whether the key is expected. `raw_spec`
SHALL remain exempt from both checks: its own internal keys are never
restricted or required, only the presence of the `raw_spec` field itself
within `registered_spec_snapshot`.

#### Scenario: An unrecognized top-level envelope field fails closed
- **WHEN** a `schema_version = 1` line's envelope contains a field outside
  `schema_version`, `strategy_instance_id`, `strategy_id`,
  `registered_spec_snapshot`, `risk_multiplier`, and `current_trade_cycle`,
  or a `schema_version = 2` line's envelope contains a field outside that
  same set plus `pending_entry_recovery`
- **THEN** decoding raises a schema/domain validation failure
- **AND** replay applies this exactly like any other such failure — fail
  closed on any line, and fail closed even when confined to the last line

#### Scenario: An unrecognized field inside a nested structure fails closed
- **WHEN** `registered_spec_snapshot`, `current_trade_cycle`,
  `applied_entry_package`, `desired_entry`, `frozen_entry_context`,
  `latest_confirmed_management_protection`, or (for a `schema_version = 2`
  line) `pending_entry_recovery` contains a field outside that structure's
  exact allowed set
- **THEN** decoding raises a schema/domain validation failure, with the
  same fail-closed replay handling as any other invalid record

#### Scenario: A missing nullable field fails closed instead of decoding as null
- **WHEN** a persisted structure omits a key that its schema defines as
  nullable for that line's `schema_version` — `current_trade_cycle` on the
  envelope, `frozen_entry_context` or `latest_confirmed_management_protection`
  on `CurrentTradeCycle`, `take_price` on
  `latest_confirmed_management_protection`, or, for a `schema_version = 2`
  line only, `pending_entry_recovery` on the envelope — rather than including
  that key with a JSON `null` value
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

## ADDED Requirements

### Requirement: Decoding dispatches by schema_version, supporting exactly versions 1 and 2
`JsonlStrategyInstanceRuntimeStateRepository`'s codec SHALL accept exactly two
values of the envelope's `schema_version` field: `1` and `2`. A
`schema_version = 1` line decodes without a `pending_entry_recovery` field,
which SHALL be treated as `pending_entry_recovery = None` on the decoded
aggregate. A `schema_version = 2` line requires the `pending_entry_recovery`
key to be present, holding either `null` or a complete `PendingEntryRecovery`
object (`trade_cycle_id` only — no timestamp field). Every new write (`save`,
and the creation path of `get_or_create`) SHALL encode `schema_version = 2`. Any
other `schema_version` value SHALL fail closed exactly like any other
schema/domain validation failure.

#### Scenario: A schema_version 1 line decodes with no pending recovery marker
- **WHEN** replay encounters a line with `schema_version: 1` and no
  `pending_entry_recovery` key
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_entry_recovery` is `None`

#### Scenario: A schema_version 2 line requires the pending recovery key
- **WHEN** replay encounters a line with `schema_version: 2` that omits the
  `pending_entry_recovery` key
- **THEN** decoding raises a schema/domain validation failure, per the exact-
  key-set requirement's nullable-field rule

#### Scenario: A schema_version 2 line with a null marker decodes normally
- **WHEN** replay encounters a line with `schema_version: 2` and
  `pending_entry_recovery: null`
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_entry_recovery` is `None`

#### Scenario: A schema_version 2 line with a present marker decodes it
- **WHEN** replay encounters a line with `schema_version: 2` and
  `pending_entry_recovery` holding a complete `{trade_cycle_id}` object
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_entry_recovery` holds that exact
  `trade_cycle_id`

#### Scenario: Every new write is schema_version 2
- **WHEN** `save(...)` or the creation path of `get_or_create(...)` encodes a
  line
- **THEN** the encoded envelope's `schema_version` is `2`
- **AND** it includes the `pending_entry_recovery` key, `null` or a complete
  object, never omitted

#### Scenario: An unsupported schema_version fails closed
- **WHEN** replay encounters a line whose `schema_version` is neither `1` nor
  `2`, or is missing
- **THEN** decoding raises a schema/domain validation failure, with the same
  fail-closed replay handling as any other invalid record

#### Scenario: No rewrite of existing schema_version 1 lines
- **WHEN** the durable file contains `schema_version = 1` lines for
  instances that have not been saved again since this change
- **THEN** replay reads them successfully as `pending_entry_recovery = None`
- **AND** no migration, rewrite, or compaction of those lines occurs — they
  remain `schema_version = 1` until that instance's next `save()` writes a
  fresh `schema_version = 2` line
