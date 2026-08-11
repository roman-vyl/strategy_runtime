# strategy-runtime-docker Specification

## Purpose
Define the container/process/filesystem/network/mount contract for packaging and running Strategy Runtime as a single production Docker container, over the already-ratified application architecture and Live V1 semantics.

## Requirements
### Requirement: Container runs the existing Runtime process directly, as a non-root PID 1
The Strategy Runtime Docker image SHALL run the existing `strategy-runtime`
production entrypoint directly as the container's main process, with no
shell, init system, or supervisor interposed, and SHALL run as a
dedicated non-root user.

#### Scenario: Exec-form entrypoint with no shell wrapper
- **WHEN** the image's `ENTRYPOINT` is inspected
- **THEN** it invokes `strategy-runtime` in exec form (a JSON array, not a
  shell string)
- **AND** no `sh -c`, `bash -c`, or equivalent shell wrapper is present
- **AND** no supervisor process (e.g. `tini`, `supervisord`) is added
  ahead of it

#### Scenario: Runs as a non-root user
- **WHEN** the container starts
- **THEN** the main process runs as a dedicated non-root user created in
  the image, not as `root` and not as an arbitrary UID with root
  privileges

### Requirement: In-container bind on 0.0.0.0:8093, host publishing restricted to loopback
The image SHALL default the Runtime process to bind on `0.0.0.0:8093`
inside the container. Deployment configuration (Compose file or
documented `docker run` invocation) in this repository SHALL publish that
port to the host only on the loopback interface.

#### Scenario: Image default binds on all interfaces inside the container
- **WHEN** the container starts with no `RUNTIME_HOST`/`RUNTIME_PORT`
  override
- **THEN** the Runtime process listens on `0.0.0.0:8093` inside the
  container's network namespace

#### Scenario: Host publishing is loopback-only
- **WHEN** the repository's `docker-compose.yml` or documented `docker
  run` invocation publishes the container's port 8093
- **THEN** it publishes as `127.0.0.1:8093:8093` — never a bare
  `8093:8093` or a non-loopback host address

### Requirement: Engine and ABI URLs come only from Runtime environment configuration
The Docker image SHALL NOT hardcode a Strategy Engine or ABI base URL.
Every Engine/ABI base URL and timeout the container uses SHALL come from
the existing `RUNTIME_STRATEGY_ENGINE_BASE_URL`/`RUNTIME_ABI_BASE_URL`
(and their timeout counterparts) Runtime environment configuration,
unchanged from the already-ratified `runtime-production-composition`
fail-closed configuration gate.

#### Scenario: No baked-in service URL
- **WHEN** the `Dockerfile` and any repository-provided Compose file are
  inspected
- **THEN** no `RUNTIME_STRATEGY_ENGINE_BASE_URL` or `RUNTIME_ABI_BASE_URL`
  value is hardcoded as a fixed default inside the image or as a
  non-overridable Compose value
- **AND** any example value in documentation or Compose is clearly a
  placeholder, overridable via the shell environment

### Requirement: This repository packages only Strategy Runtime
No Compose file, Dockerfile, or other build artifact in this repository
SHALL define or build a Strategy Engine, ABI, or Market Data Service
container.

#### Scenario: Single-service Compose file
- **WHEN** `docker-compose.yml` is inspected
- **THEN** it defines exactly one service, for Strategy Runtime
- **AND** no Engine, ABI, or MDS service, network alias, or build
  context is present

### Requirement: Read-only specs mount, one writable journal mount, no other writable path
The container SHALL treat `RUNTIME_SPECS_PATH` as a read-only mount and
`RUNTIME_JOURNAL_PATH` as the one writable, persistent mount it requires.
The container SHALL start and operate correctly with a read-only root
filesystem plus exactly these two mounts, with no other writable
filesystem path required.

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

### Requirement: Reused health contract as the Docker HEALTHCHECK
The image's Docker `HEALTHCHECK` SHALL probe one of Runtime's existing
`/health/live` or `/health/ready` endpoints, unmodified. This change
SHALL NOT introduce a new health endpoint or change either endpoint's
existing semantics for the sake of Docker-specific unification with any
other service's health contract.

#### Scenario: HEALTHCHECK targets an existing endpoint
- **WHEN** the image's `HEALTHCHECK` instruction is inspected
- **THEN** it issues a request against `/health/ready` (or `/health/live`)
  on the container's own bound port
- **AND** no new endpoint, and no change to either endpoint's existing
  response contract, is introduced by this change

### Requirement: Direct SIGTERM handling and graceful shutdown
Because the main process runs directly as PID 1 with no shell or
supervisor interposed, it SHALL receive `SIGTERM` directly from the
container runtime and SHALL shut down through Runtime's existing lifespan
shutdown sequence without requiring `SIGKILL`.

#### Scenario: Graceful shutdown on stop
- **WHEN** the container receives a stop signal (`docker stop` or
  Compose's equivalent)
- **THEN** the main process receives `SIGTERM` directly
- **AND** it completes Runtime's existing shutdown sequence and exits on
  its own before the runtime's kill timeout elapses, with no `SIGKILL`
  required

### Requirement: Fail-closed startup on invalid configuration or not-ready composition
The container SHALL NOT begin serving requests when Runtime's production
configuration is invalid or when composition reports `ready=False`,
consistent with the existing `strategy-runtime` entrypoint behavior.

#### Scenario: Invalid configuration refuses to start
- **WHEN** the container is started with a missing or invalid required
  Runtime environment variable
- **THEN** the process exits with a non-zero status instead of serving
  requests

#### Scenario: Not-ready composition refuses to start
- **WHEN** application composition reports `ready=False` for any other
  reason
- **THEN** the process exits with a non-zero status instead of serving
  requests

### Requirement: Strict build context
The Docker build context for this repository SHALL exclude tests,
OpenSpec content, version control metadata, caches, and other
build-time-irrelevant artifacts.

#### Scenario: Build context excludes non-runtime content
- **WHEN** `docker build` runs against the repository root
- **THEN** the effective build context (as filtered by `.dockerignore`)
  contains no `.git`, `tests/`, `openspec/`, `.venv/`, `__pycache__/`,
  lint/type-check cache directories, `node_modules/`, editor/agent
  metadata directories, or `.env` files
- **AND** the files the `Dockerfile` actually `COPY`s (`pyproject.toml`,
  `README.md`, `src/`) remain present in the filtered context
