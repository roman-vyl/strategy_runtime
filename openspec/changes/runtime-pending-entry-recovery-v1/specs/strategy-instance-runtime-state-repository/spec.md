## ADDED Requirements

### Requirement: Repository enumerates instances with a pending entry-recovery marker
`StrategyInstanceRuntimeStateRepository` SHALL expose
`list_ids_with_pending_entry_mutation() -> tuple[str, ...]`, a read-only
filter returning every currently registered `strategy_instance_id` whose
stored state has a non-null `pending_entry_recovery`. This is the only
enumeration this repository exposes; it SHALL NOT introduce a general
`list_all()` or any other bulk-read operation, and it introduces no new
durable structure — the returned identities are derived entirely from the
existing per-instance aggregate already held by `get`/`get_or_create`/`save`.

#### Scenario: Enumerate only pending instances
- **WHEN** some registered instances have a non-null `pending_entry_recovery`
  and others do not
- **THEN** `list_ids_with_pending_entry_mutation()` returns exactly the
  `strategy_instance_id` values of the instances with a non-null marker
- **AND** omits every instance whose `pending_entry_recovery` is null

#### Scenario: Empty result when nothing is pending
- **WHEN** no registered instance has a non-null `pending_entry_recovery`
- **THEN** `list_ids_with_pending_entry_mutation()` returns an empty tuple

#### Scenario: Reflects durable state immediately after restart
- **WHEN** the repository is constructed against a durable store containing
  instances with a non-null `pending_entry_recovery`
- **THEN** `list_ids_with_pending_entry_mutation()` returns those instances'
  identities immediately after construction, with no additional read or
  replay step beyond the repository's existing startup recovery

#### Scenario: Keep downstream processing outside the repository
- **WHEN** `list_ids_with_pending_entry_mutation()` returns
- **THEN** the repository has not called ABI, acquired a keyed mutex, or
  performed any resolution logic — it returns identities only
