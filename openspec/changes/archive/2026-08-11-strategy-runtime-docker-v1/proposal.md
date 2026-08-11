## Why

Strategy Runtime's application architecture and Live V1 semantics are
ratified and unchanged. The repository already ships a working `Dockerfile`,
a non-root exec-form entrypoint, and a documented mount contract in the
README, but no canonical OpenSpec capability describes the container's
process, filesystem, and network contract — so there is no ratified
definition of what "Docker-ready" means for this repository, and no
guardrail against a future change silently breaking it (running under a
shell wrapper, binding only to loopback, requiring a second writable path,
or pulling Engine/ABI containers into this repo). This change canonizes the
existing, working container contract and closes two small implementation
gaps found while reviewing it against production-readiness requirements:
the image did not default `RUNTIME_HOST` to `0.0.0.0`, and no minimal
Compose file existed for local/production single-service orchestration.

## What Changes

- Canonize the existing container/process/filesystem/network/mount
  contract as a new `strategy-runtime-docker` capability: direct
  exec-form PID 1 process (no shell, no supervisor), non-root user,
  in-container bind on `0.0.0.0:8093`, host publishing restricted to
  `127.0.0.1:8093`, Engine/ABI URLs sourced only from Runtime environment
  configuration, no Engine/ABI/MDS service in this repository, read-only
  specs mount, one writable journal mount and no other writable path
  (compatible with `--read-only` root filesystem), the existing
  `/health/live`/`/health/ready` endpoints reused unmodified as the
  container probes and Docker `HEALTHCHECK`, direct `SIGTERM` delivery to
  the main process, journal persistence across remove/recreate on the same
  mount, clean startup on an empty journal mount, fail-closed refusal to
  serve on invalid configuration or `ready=False`, and a build context
  free of tests/OpenSpec/git/cache/build artifacts.
- `Dockerfile`: default `ENV RUNTIME_HOST=0.0.0.0` (and keep
  `RUNTIME_PORT=8093`) so the image satisfies the in-container bind
  requirement without every caller having to remember to pass it.
- `.dockerignore`: extend the existing exclusion list with `.github`,
  `.env`/`.env.*` (with the existing `.example` negation pattern),
  `docker-compose*.yml`, and non-README markdown, tightening the build
  context beyond what was already excluded.
- Add a minimal `docker-compose.yml` that runs only the Runtime service:
  `127.0.0.1:8093:8093`, `read_only: true`, a read-only specs bind mount,
  a writable journal bind mount, and Engine/ABI base URLs sourced from the
  shell environment — no Engine/ABI/MDS service defined.
- README `## Docker` section: document the image's `0.0.0.0` default, the
  read-only-root-filesystem-compatible mount contract, the reused health
  contract, `SIGTERM` handling, and the new Compose file.

## Non-Goals

- No change to Runtime orchestration, Engine/ABI HTTP contracts,
  repository/mutex semantics, entry/open-trade/position-management logic,
  or acknowledgement semantics.
- No change to `runtime-production-composition`'s graph, configuration
  gating, or lifecycle-ownership requirements — this change consumes that
  capability's existing fail-closed startup behavior and existing
  `/health/live`/`/health/ready` endpoints as-is.
- No change to the processing-journal's own persistence model beyond the
  already-existing requirement that its configured path be a mounted,
  writable location — this change only canonizes the container-level mount
  contract around it.
- No multi-service system composition: Engine, ABI, and MDS containers are
  explicitly out of scope and are not added to this repository.
- No new or different health-check semantics: the existing
  `/health/ready` endpoint is reused unmodified as the Docker
  `HEALTHCHECK` target.

## Capabilities

### Added Capabilities

- `strategy-runtime-docker`: the container/process/filesystem/network/mount
  contract for packaging and running Strategy Runtime as a single
  production Docker container.

## Impact

- Touches `Dockerfile`, `.dockerignore`, `README.md` (the existing
  `## Docker` section), and adds `docker-compose.yml` at the repository
  root.
- No `src/` or `tests/` change — this is a packaging-and-documentation
  change over an already-complete application.
