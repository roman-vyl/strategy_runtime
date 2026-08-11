## 1. Implementation

- [x] 1.1 `docker-compose.yml`: change the specs bind-mount `source` from
  `./var/specs` to `${BBB_DATA_ROOT}/strategy-runtime/specs`; keep
  `target: /runtime/specs` and `read_only: true`.
- [x] 1.2 `docker-compose.yml`: change the journal bind-mount `source`
  from `./var/journal` to `${BBB_DATA_ROOT}/strategy-runtime/journal`;
  keep `target: /runtime/journal` (writable).
- [x] 1.3 README `## Docker`: update the `docker run` example and the
  Compose description to the `${BBB_DATA_ROOT}/strategy-runtime/...`
  host paths; note `./var/specs`/`./var/journal` are local dev-only
  scratch paths, not used by Compose or documented `docker run`.

## 2. Verification (this change's pass)

- [x] 2.1 `docker compose config` with an explicit temporary
  `BBB_DATA_ROOT` resolves specs source to
  `<BBB_DATA_ROOT>/strategy-runtime/specs` (read-only) and journal source
  to `<BBB_DATA_ROOT>/strategy-runtime/journal` (writable), with
  container targets unchanged.
- [x] 2.2 Confirmed no remaining `./var/specs` or `./var/journal`
  reference in `docker-compose.yml` or the README `## Docker` section.
- [x] 2.3 `npm exec -- openspec validate runtime-bbb-data-root-v1
  --strict` passes.
- [x] 2.4 `npm exec -- openspec validate --all --strict` passes with no
  regression to any existing spec.
- [x] 2.5 `git diff --check` clean.
- [x] 2.6 Confirmed no change to `InMemoryStrategyInstanceRuntimeStateRepository`,
  processing-journal implementation, container-internal paths, or
  Engine/ABI URL configuration.
