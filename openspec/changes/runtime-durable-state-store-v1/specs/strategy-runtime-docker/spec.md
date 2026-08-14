## MODIFIED Requirements

### Requirement: Read-only specs mount, one writable journal mount, no other writable path
The container SHALL treat `RUNTIME_SPECS_PATH` as a read-only mount,
`RUNTIME_JOURNAL_PATH` as one writable, persistent mount, and
`RUNTIME_STATE_PATH` as a second writable, persistent mount for the
durable strategy-instance state store. The container SHALL start and
operate correctly with a read-only root filesystem plus exactly these
three mounts, with no other writable filesystem path required.

Production/local Compose SHALL source these three mounts from the shared
BBB data root convention already used by Market Data Service
(`${BBB_DATA_ROOT}/market-data`): the specs mount SHALL source from
`${BBB_DATA_ROOT}/strategy-runtime/specs`, the journal mount SHALL source
from `${BBB_DATA_ROOT}/strategy-runtime/journal`, and the state mount
SHALL source from `${BBB_DATA_ROOT}/strategy-runtime/state`. The
repository-local `./var/specs`, `./var/journal`, and `./var/state` paths
are not production/local Compose storage. This host-side placement does
not change container-internal paths and does not change
processing-journal semantics — it relocates only where the mount sources
live on the host, and it is this change (not the mount relocation) that
makes strategy-instance state durable.

Compose SHALL require `BBB_DATA_ROOT` to be set, failing closed with no
empty-path substitution when it is not — the same fail-closed convention
already applied to ABI's Compose configuration.

#### Scenario: Specs mount is read-only
- **WHEN** the container is run with `RUNTIME_SPECS_PATH` mounted
  read-only
- **THEN** Runtime reads deployment specs successfully
- **AND** Runtime never attempts to write to that mount

#### Scenario: Journal and state mounts are the only required writable paths
- **WHEN** the container is run with `--read-only` (or Compose
  `read_only: true`) and exactly three mounts — the read-only specs
  mount, a writable `RUNTIME_JOURNAL_PATH` mount, and a writable
  `RUNTIME_STATE_PATH` mount
- **THEN** the container starts successfully and serves `/health/ready`
  as ready
- **AND** no write outside the journal and state mounts is required for
  correct operation

#### Scenario: Journal persists across remove and recreate on the same mount
- **WHEN** the container is removed and recreated with the same
  `RUNTIME_JOURNAL_PATH` host mount
- **THEN** the JSONL processing journal content written before removal is
  still present and readable after recreation

#### Scenario: Durable state persists across remove and recreate on the same mount
- **WHEN** the container is removed and recreated with the same
  `RUNTIME_STATE_PATH` host mount
- **THEN** the durable strategy-instance state file content written
  before removal is still present after recreation
- **AND** replay on the recreated container restores the latest saved
  state for every strategy instance that had been saved before removal

#### Scenario: Clean start on an empty journal mount
- **WHEN** the container is recreated with a new, empty
  `RUNTIME_JOURNAL_PATH` mount
- **THEN** the container starts cleanly and creates a new, empty journal
  file at that path with no error

#### Scenario: Clean start on an empty state mount
- **WHEN** the container is recreated with a new, empty
  `RUNTIME_STATE_PATH` mount
- **THEN** the container starts cleanly, replay finds no prior records,
  and Runtime starts with no registered strategy-instance state — no
  error is raised solely because no prior state file exists

#### Scenario: Compose sources all three mounts from the shared BBB data root
- **WHEN** `docker-compose.yml` is resolved (e.g. via `docker compose
  config`) with `BBB_DATA_ROOT` set
- **THEN** the specs bind mount's `source` is
  `${BBB_DATA_ROOT}/strategy-runtime/specs` and is `read_only: true`
- **AND** the journal bind mount's `source` is
  `${BBB_DATA_ROOT}/strategy-runtime/journal` and is writable
- **AND** the state bind mount's `source` is
  `${BBB_DATA_ROOT}/strategy-runtime/state` and is writable
- **AND** all three mounts' `target` values remain `/runtime/specs`,
  `/runtime/journal`, and `/runtime/state` respectively

#### Scenario: Repository-local ./var is not production/local Compose storage
- **WHEN** `docker-compose.yml` and the README `## Docker` section are
  inspected
- **THEN** none references `./var/specs`, `./var/journal`, or
  `./var/state` as a Compose or documented `docker run` mount source
- **AND** any remaining `./var/specs`/`./var/journal`/`./var/state` path
  in the repository is understood as a local, non-Docker development
  default only

#### Scenario: Missing BBB_DATA_ROOT fails Compose closed
- **WHEN** `docker compose config` (or any Compose invocation) resolves
  `docker-compose.yml` with `BBB_DATA_ROOT` unset
- **THEN** Compose exits non-zero
- **AND** the error message explicitly states `BBB_DATA_ROOT must be set`
- **AND** no empty-path substitution for any of the three mount `source`
  values is produced

#### Scenario: Strategy-instance state is now durable; journal semantics are unchanged
- **WHEN** the container is run with the state mount configured
- **THEN** `JsonlStrategyInstanceRuntimeStateRepository`, not
  `InMemoryStrategyInstanceRuntimeStateRepository`, is the sole
  strategy-instance state store, and it survives restart via
  `RUNTIME_STATE_PATH`
- **AND** the JSONL processing journal's existing best-effort semantics
  remain unchanged
