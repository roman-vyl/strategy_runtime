## 1. Implementation Gaps

- [x] 1.1 `Dockerfile`: add `ENV RUNTIME_HOST=0.0.0.0` alongside the
  existing `RUNTIME_PORT=8093` default so the image binds on all
  interfaces inside the container without relying on every caller to
  pass `-e RUNTIME_HOST=0.0.0.0`.
- [x] 1.2 `.dockerignore`: add `.github`, `.env`/`.env.*` (keeping the
  `.example` negation), `docker-compose*.yml`, and non-README markdown to
  the existing exclusion list.
- [x] 1.3 Add `docker-compose.yml` at the repository root: single
  `strategy-runtime` service, `127.0.0.1:8093:8093`, `read_only: true`,
  read-only specs bind mount, writable journal bind mount, Engine/ABI
  base URLs from the shell environment — no Engine/ABI/MDS service.
- [x] 1.4 README `## Docker`: document the `0.0.0.0` default, the
  read-only-root-filesystem-compatible mount contract, the reused health
  contract, `SIGTERM` handling, and Compose usage.

## 2. Verification (this change's pass)

- [x] 2.1 `npm exec -- openspec validate strategy-runtime-docker-v1
  --strict` passes.
- [x] 2.2 `npm exec -- openspec validate --all --strict` passes with no
  regression to any existing spec.
- [x] 2.3 `make verify` (lint, format-check, typecheck, test) — confirmed
  no `src/`/`tests/` change was needed or made; any pre-existing failures
  are unrelated to this change and are not introduced by it.
- [x] 2.4 Manual review of `Dockerfile`, `.dockerignore`, and
  `docker-compose.yml` against every scenario in this change's
  `strategy-runtime-docker` spec delta, plus build-context inspection
  (via a `FROM scratch` context-export probe) confirming tests/OpenSpec/
  git/cache/build artifacts are excluded.
- [x] 2.5 Real `docker build`/`docker run` container smoke tests were
  attempted and are blocked by this sandbox's network egress policy,
  which returns 403 on all Docker Hub blob pulls (confirmed against two
  unrelated base images); this is recorded as a known verification gap
  for a networked environment to close, not a defect in the reviewed
  contract.
