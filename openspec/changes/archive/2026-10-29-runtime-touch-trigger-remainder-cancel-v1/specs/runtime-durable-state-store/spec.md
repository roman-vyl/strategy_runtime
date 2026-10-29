## RENAMED Requirements

- FROM: `### Requirement: Decoding dispatches by schema_version, supporting exactly versions 1, 2, and 3`
- TO: `### Requirement: Decoding dispatches by schema_version, supporting exactly versions 1, 2, 3, and 4`

## MODIFIED Requirements

### Requirement: Decoding dispatches by schema_version, supporting exactly versions 1, 2, 3, and 4
`JsonlStrategyInstanceRuntimeStateRepository`'s codec SHALL accept exactly
four values of the envelope's `schema_version` field: `1`, `2`, `3`, and `4`. A
`schema_version = 1` line decodes without a `pending_entry_recovery` or
`pending_close_recovery` field, both of which SHALL be treated as `None` on
the decoded aggregate. A `schema_version = 2` line requires the
`pending_entry_recovery` key to be present (`null` or a complete
`PendingEntryRecovery` object) but decodes without a `pending_close_recovery`
field, which SHALL be treated as `None`. A `schema_version = 3` line requires
both the `pending_entry_recovery` and `pending_close_recovery` keys to be
present, each holding either `null` or its complete object
(`PendingCloseRecovery` has `trade_cycle_id` only — no timestamp field, no
action discriminator). A `schema_version = 4` line has the same envelope as
version 3 and additionally requires `current_trade_cycle.entry_remainder_cancelled`
(boolean) and, on a non-null `frozen_entry_context`, the
`entry_order_expires_at_bar` key (integer or `null`). Lines of versions 1–3
decode with `entry_remainder_cancelled = false` and
`entry_order_expires_at_bar = null`, and SHALL reject those keys if present.
Every new write (`save`, and the creation path of `get_or_create`) SHALL
encode `schema_version = 4`. Any other
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
- **THEN** the encoded envelope's `schema_version` is `4` (this scenario keeps
  its historical name; version 4 superseded version 3 for new writes)
- **AND** it includes both the `pending_entry_recovery` and
  `pending_close_recovery` keys, each `null` or a complete object, never
  omitted

#### Scenario: An unsupported schema_version fails closed
- **WHEN** replay encounters a line whose `schema_version` is not one of
  `1`, `2`, `3`, or `4`, or is missing
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
  `save()` writes a fresh `schema_version = 4` line

#### Scenario: A schema_version 4 line carries the remainder fields
- **WHEN** replay encounters a `schema_version: 4` line whose current trade cycle has
  `entry_remainder_cancelled` and whose frozen context has `entry_order_expires_at_bar`
- **THEN** decoding succeeds with those exact values

#### Scenario: A schema_version 4 line missing a remainder key fails closed
- **WHEN** a `schema_version: 4` line's current trade cycle omits `entry_remainder_cancelled`,
  or its non-null frozen context omits `entry_order_expires_at_bar`
- **THEN** decoding raises a schema/domain validation failure

#### Scenario: Older lines decode with remainder defaults
- **WHEN** replay encounters a `schema_version` 1, 2 or 3 line with a frozen cycle
- **THEN** the decoded cycle has `entry_remainder_cancelled = false` and `entry_order_expires_at_bar = null`
