## MODIFIED Requirements

### Requirement: Read-only specs mount, one writable journal mount, no other writable path
The container SHALL treat `RUNTIME_SPECS_PATH` as a read-only mount and
`RUNTIME_JOURNAL_PATH` as the one writable, persistent mount it requires.
The container SHALL start and operate correctly with a read-only root
filesystem plus exactly these two mounts, with no other writable
filesystem path required.

Production/local Compose SHALL source these two mounts from the shared
BBB data root convention already used by Market Data Service
(`${BBB_DATA_ROOT}/market-data`): the specs mount SHALL source from
`${BBB_DATA_ROOT}/strategy-runtime/specs` and the journal mount SHALL
source from `${BBB_DATA_ROOT}/strategy-runtime/journal`. The
repository-local `./var/specs` and `./var/journal` paths are not
production/local Compose storage. This host-side placement does not
change container-internal paths, does not make strategy-instance state
durable, and does not change processing-journal semantics — it relocates
only where the two existing mount sources live on the host.

#### Scenario: Specs mount is read-only
- **WHEN** the container is run with `RUNTIME_SPECS_PATH` mounted
  read-only
- **THEN** Runtime reads deployment specs successfully
- **AND** Runtime never attempts to write to that mount

#### Scenario: Journal mount is the only required writable path
- **WHEN** the container is run with `--read-only` (or Compose
  `read_only: true`) and exactly two mounts — the read-only specs mount
  and a writable `RUNTIME_JOURNAL_PATH` mount
- **THEN** the container starts successfully and serves `/health/ready`
  as ready
- **AND** no write outside the journal mount is required for correct
  operation

#### Scenario: Journal persists across remove and recreate on the same mount
- **WHEN** the container is removed and recreated with the same
  `RUNTIME_JOURNAL_PATH` host mount
- **THEN** the JSONL processing journal content written before removal is
  still present and readable after recreation

#### Scenario: Clean start on an empty journal mount
- **WHEN** the container is recreated with a new, empty
  `RUNTIME_JOURNAL_PATH` mount
- **THEN** the container starts cleanly and creates a new, empty journal
  file at that path with no error

#### Scenario: Compose sources both mounts from the shared BBB data root
- **WHEN** `docker-compose.yml` is resolved (e.g. via `docker compose
  config`) with `BBB_DATA_ROOT` set
- **THEN** the specs bind mount's `source` is
  `${BBB_DATA_ROOT}/strategy-runtime/specs` and is `read_only: true`
- **AND** the journal bind mount's `source` is
  `${BBB_DATA_ROOT}/strategy-runtime/journal` and is writable
- **AND** both mounts' `target` values remain `/runtime/specs` and
  `/runtime/journal` respectively

#### Scenario: Repository-local ./var is not production/local Compose storage
- **WHEN** `docker-compose.yml` and the README `## Docker` section are
  inspected
- **THEN** neither references `./var/specs` or `./var/journal` as a
  Compose or documented `docker run` mount source
- **AND** any remaining `./var/specs`/`./var/journal` path in the
  repository is understood as a local, non-Docker development default
  only

#### Scenario: No change to durability or journal semantics
- **WHEN** the host-side mount source changes to the BBB data root
- **THEN** `InMemoryStrategyInstanceRuntimeStateRepository` remains the
  sole strategy-instance state store, still non-durable and lost on
  restart
- **AND** the JSONL processing journal's existing best-effort semantics
  are unchanged — only its host-side directory moved
