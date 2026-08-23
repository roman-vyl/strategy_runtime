## MODIFIED Requirements

### Requirement: Decoding enforces the exact key set of every persisted structure except `raw_spec`
Decoding a durable JSONL line SHALL reject, as a schema/domain validation
failure, any field not in the exact allowed set for the envelope,
`RegisteredSpecSnapshot`, `CurrentTradeCycle`, `AppliedEntryPackage`,
`DesiredEntry`, `FrozenExecutedEntryContext`, `DesiredProtection`,
`PendingEntryRecovery`, and `PendingCloseRecovery`, and SHALL equally reject
any of those structures' fields being absent — including a nullable field
such as `current_trade_cycle`, `frozen_entry_context`,
`latest_confirmed_management_protection`, `DesiredProtection.take_price`,
(for a `schema_version = 2` or later line) `pending_entry_recovery`, or (for
a `schema_version = 3` line) `pending_close_recovery`. A record is a
complete snapshot: a nullable field MUST still be present with an explicit
JSON `null`; omitting the key is a schema violation, not an implicit null,
and decoding SHALL NOT treat a missing key the same as a present key holding
`null`. The envelope's exact allowed key set is itself version-dependent
(see "Decoding dispatches by `schema_version`, supporting exactly versions
1, 2, and 3"): a `schema_version = 1` envelope's allowed set has neither
`pending_entry_recovery` nor `pending_close_recovery`; a `schema_version = 2`
envelope's allowed set adds `pending_entry_recovery` but not
`pending_close_recovery`; their absence at those versions is not a violation
of this requirement — it is the version-specific rule that governs whether
each key is expected. `raw_spec` SHALL remain exempt from both checks: its
own internal keys are never restricted or required, only the presence of the
`raw_spec` field itself within `registered_spec_snapshot`.

#### Scenario: An unrecognized top-level envelope field fails closed
- **WHEN** a `schema_version = 1` line's envelope contains a field outside
  `schema_version`, `strategy_instance_id`, `strategy_id`,
  `registered_spec_snapshot`, `risk_multiplier`, and `current_trade_cycle`;
  a `schema_version = 2` line's envelope contains a field outside that same
  set plus `pending_entry_recovery`; or a `schema_version = 3` line's
  envelope contains a field outside that same set plus
  `pending_close_recovery`
- **THEN** decoding raises a schema/domain validation failure
- **AND** replay applies this exactly like any other such failure — fail
  closed on any line, and fail closed even when confined to the last line

#### Scenario: An unrecognized field inside a nested structure fails closed
- **WHEN** `registered_spec_snapshot`, `current_trade_cycle`,
  `applied_entry_package`, `desired_entry`, `frozen_entry_context`,
  `latest_confirmed_management_protection`, (for a `schema_version = 2` or
  later line) `pending_entry_recovery`, or (for a `schema_version = 3` line)
  `pending_close_recovery` contains a field outside that structure's exact
  allowed set
- **THEN** decoding raises a schema/domain validation failure, with the
  same fail-closed replay handling as any other invalid record

#### Scenario: A missing nullable field fails closed instead of decoding as null
- **WHEN** a persisted structure omits a key that its schema defines as
  nullable for that line's `schema_version` — `current_trade_cycle` on the
  envelope, `frozen_entry_context` or `latest_confirmed_management_protection`
  on `CurrentTradeCycle`, `take_price` on
  `latest_confirmed_management_protection`, `pending_entry_recovery` on the
  envelope for a `schema_version = 2` or later line, or
  `pending_close_recovery` on the envelope for a `schema_version = 3` line —
  rather than including that key with a JSON `null` value
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

### Requirement: Decoding dispatches by schema_version, supporting exactly versions 1, 2, and 3
`JsonlStrategyInstanceRuntimeStateRepository`'s codec SHALL accept exactly
three values of the envelope's `schema_version` field: `1`, `2`, and `3`. A
`schema_version = 1` line decodes without a `pending_entry_recovery` or
`pending_close_recovery` field, both of which SHALL be treated as `None` on
the decoded aggregate. A `schema_version = 2` line requires the
`pending_entry_recovery` key to be present (`null` or a complete
`PendingEntryRecovery` object) but decodes without a `pending_close_recovery`
field, which SHALL be treated as `None`. A `schema_version = 3` line requires
both the `pending_entry_recovery` and `pending_close_recovery` keys to be
present, each holding either `null` or its complete object
(`PendingCloseRecovery` has `trade_cycle_id` only — no timestamp field, no
action discriminator). Every new write (`save`, and the creation path of
`get_or_create`) SHALL encode `schema_version = 3`. Any other
`schema_version` value SHALL fail closed exactly like any other
schema/domain validation failure.

#### Scenario: A schema_version 1 line decodes with neither pending marker
- **WHEN** replay encounters a line with `schema_version: 1` and neither a
  `pending_entry_recovery` nor a `pending_close_recovery` key
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_entry_recovery` and
  `pending_close_recovery` are both `None`

#### Scenario: A schema_version 2 line decodes with no pending close marker
- **WHEN** replay encounters a line with `schema_version: 2`, a present
  `pending_entry_recovery` key, and no `pending_close_recovery` key
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_close_recovery` is `None`

#### Scenario: A schema_version 3 line requires both pending marker keys
- **WHEN** replay encounters a line with `schema_version: 3` that omits
  either the `pending_entry_recovery` or the `pending_close_recovery` key
- **THEN** decoding raises a schema/domain validation failure, per the
  exact-key-set requirement's nullable-field rule

#### Scenario: A schema_version 3 line with both markers null decodes normally
- **WHEN** replay encounters a line with `schema_version: 3`,
  `pending_entry_recovery: null`, and `pending_close_recovery: null`
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_entry_recovery` and
  `pending_close_recovery` are both `None`

#### Scenario: A schema_version 3 line with a present close marker decodes it
- **WHEN** replay encounters a line with `schema_version: 3` and
  `pending_close_recovery` holding a complete `{trade_cycle_id}` object
- **THEN** decoding succeeds
- **AND** the decoded aggregate's `pending_close_recovery` holds that exact
  `trade_cycle_id`

#### Scenario: A schema_version 3 line with both markers non-null fails closed
- **WHEN** replay encounters a line with `schema_version: 3` where both
  `pending_entry_recovery` and `pending_close_recovery` hold non-null values
- **THEN** decoding raises a schema/domain validation failure, per
  `pending-close-recovery-state`'s mutual-exclusion invariant, with the same
  fail-closed replay handling as any other invalid record

#### Scenario: Every new write is schema_version 3
- **WHEN** `save(...)` or the creation path of `get_or_create(...)` encodes a
  line
- **THEN** the encoded envelope's `schema_version` is `3`
- **AND** it includes both the `pending_entry_recovery` and
  `pending_close_recovery` keys, each `null` or a complete object, never
  omitted

#### Scenario: An unsupported schema_version fails closed
- **WHEN** replay encounters a line whose `schema_version` is not one of
  `1`, `2`, or `3`, or is missing
- **THEN** decoding raises a schema/domain validation failure, with the same
  fail-closed replay handling as any other invalid record

#### Scenario: No rewrite of existing schema_version 1 or 2 lines
- **WHEN** the durable file contains `schema_version = 1` or
  `schema_version = 2` lines for instances that have not been saved again
  since this change
- **THEN** replay reads them successfully, treating any absent
  `pending_close_recovery` (and, for version 1, absent
  `pending_entry_recovery`) as `None`
- **AND** no migration, rewrite, or compaction of those lines occurs — they
  remain at their original `schema_version` until that instance's next
  `save()` writes a fresh `schema_version = 3` line
