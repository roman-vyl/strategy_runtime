## Why

Market Data Service already stores its host-side data under a shared BBB
data root convention: `${BBB_DATA_ROOT}/market-data:/data`. Strategy
Runtime's `docker-compose.yml` (added by `strategy-runtime-docker-v1`)
instead bound its two mounts to repository-local `./var/specs` and
`./var/journal`, which puts host-side Runtime data inside this
repository's working tree instead of the shared data root every other BBB
service already uses. This change moves only the host-side mount source
to match the established convention; nothing about the container's
internal paths, the application, or Live V1 state semantics changes.

## What Changes

- `docker-compose.yml`: change the two bind-mount `source` values from
  `./var/specs` / `./var/journal` to
  `${BBB_DATA_ROOT}/strategy-runtime/specs` /
  `${BBB_DATA_ROOT}/strategy-runtime/journal`. Container-internal targets
  (`/runtime/specs`, `/runtime/journal`), the read-only/writable mode of
  each mount, `read_only: true`, and the `127.0.0.1:8093:8093` publish
  binding are unchanged.
- README `## Docker` section: replace the `./var/specs`/`./var/journal`
  references in the `docker run` example and the Compose description with
  the `${BBB_DATA_ROOT}/strategy-runtime/...` paths, and note that the
  repository's own `./var/specs`/`./var/journal` are local dev-only
  scratch paths not used by Compose or by any documented `docker run`
  invocation.
- `strategy-runtime-docker` OpenSpec capability: modify the existing
  "Read-only specs mount, one writable journal mount, no other writable
  path" requirement to additionally specify the host-side mount-source
  convention for production/local Compose.

## Non-Goals

- No change to `InMemoryStrategyInstanceRuntimeStateRepository`, the
  non-durable Live V1 state semantics, or the JSONL processing-journal
  implementation.
- No change to container-internal paths (`/runtime/specs`,
  `/runtime/journal`), Runtime application/config/orchestration
  semantics, or Engine/ABI URLs.
- No `Dockerfile` change — nothing about the image itself is affected by
  where the host places the two mount sources.
- Does not make strategy-instance state durable and does not change
  processing-journal semantics; the journal mount still only persists the
  same best-effort JSONL log across container recreation, as before.

## Capabilities

### Modified Capabilities

- `strategy-runtime-docker`: the "Read-only specs mount, one writable
  journal mount, no other writable path" requirement gains the host-side
  mount-source convention (`${BBB_DATA_ROOT}/strategy-runtime/specs` and
  `${BBB_DATA_ROOT}/strategy-runtime/journal`) for production/local
  Compose; the container-side contract (read-only specs, writable
  journal, no other writable path) is unchanged.

## Impact

- Touches `docker-compose.yml` and `README.md` only. No `src/` or
  `tests/` change.
