## ADDED Requirements

### Requirement: Repository enumerates instances with a pending close-recovery marker
`StrategyInstanceRuntimeStateRepository` SHALL expose
`list_ids_with_pending_close_recovery() -> tuple[str, ...]`, a read-only
filter returning every currently registered `strategy_instance_id` whose
stored state has a non-null `pending_close_recovery`, symmetric to
`list_ids_with_pending_entry_recovery()`. It introduces no new durable
structure — the returned identities are derived entirely from the existing
per-instance aggregate already held by `get`/`get_or_create`/`save`.

#### Scenario: Enumerate only pending-close instances
- **WHEN** some registered instances have a non-null `pending_close_recovery`
  and others do not
- **THEN** `list_ids_with_pending_close_recovery()` returns exactly the
  `strategy_instance_id` values of the instances with a non-null marker
- **AND** omits every instance whose `pending_close_recovery` is null

#### Scenario: Empty result when nothing is pending
- **WHEN** no registered instance has a non-null `pending_close_recovery`
- **THEN** `list_ids_with_pending_close_recovery()` returns an empty tuple

#### Scenario: Reflects durable state immediately after restart
- **WHEN** the repository is constructed against a durable store containing
  instances with a non-null `pending_close_recovery`
- **THEN** `list_ids_with_pending_close_recovery()` returns those instances'
  identities immediately after construction, with no additional read or
  replay step beyond the repository's existing startup recovery

#### Scenario: Keep downstream processing outside the repository
- **WHEN** `list_ids_with_pending_close_recovery()` returns
- **THEN** the repository has not called ABI, acquired a keyed mutex, or
  performed any resolution logic — it returns identities only

#### Scenario: Independent of the entry-recovery enumeration
- **WHEN** an instance has a non-null `pending_entry_recovery` but a null
  `pending_close_recovery`, or vice versa
- **THEN** it appears in exactly one of
  `list_ids_with_pending_entry_recovery()` /
  `list_ids_with_pending_close_recovery()`, never both, never neither
  incorrectly
