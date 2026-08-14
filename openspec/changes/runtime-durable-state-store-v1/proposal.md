## Why

`StrategyInstanceRuntimeState` — canonical `risk_multiplier`, `CurrentTradeCycle`,
and the applied entry package / frozen first-fill context inside it — lives only
in `InMemoryStrategyInstanceRuntimeStateRepository`. Every Runtime stop, restart,
or container recreate loses it, forcing manual reconstruction of in-flight trade
cycles before Runtime can safely resume. This change makes that state survive
restart so Runtime resumes each strategy instance's lifecycle unattended.

This is not general Runtime durability. Only the strategy-instance state
aggregate becomes durable. `CommittedBarIntakeBoundary`, webhook/FIFO delivery,
redelivery of closed bars, and MDS catch-up remain non-durable and out of scope.

## What Changes

- introduce `JsonlStrategyInstanceRuntimeStateRepository`: a file-backed
  `StrategyInstanceRuntimeStateRepository` implementation backed by one shared
  append-only JSONL file, keyed by `strategy_instance_id`, where the latest
  valid record for a key is that key's current state;
- guarantee that a successful `save(...)` has already been serialized,
  appended, flushed, and `fsync`'d before returning — durability is
  correctness-critical, not best-effort;
- replay the durable file to restore every strategy instance's latest valid
  snapshot before Runtime reports ready, with no ABI- or Engine-derived
  reconstruction;
- validate every replayed record against the full state schema; fail closed
  on any record that parses as valid JSON but fails schema/domain
  validation — regardless of its position, including the last line — while
  tolerating exactly one case — the *last* line failing to parse as JSON at
  all, a truncated write left by a crash mid-append — by discarding it and
  keeping that key's last complete prior snapshot;
- keep `processing_journal` a separate, still-best-effort observability file;
  this durable store is a different file with different correctness semantics
  and is never recovered from journal content;
- keep the existing `get_or_create` / `get` / `save` port contract, its
  full-snapshot (no diff/patch/merge) `save` semantics, and the existing
  `StrategyInstanceKeyedMutexRegistry` business-level per-instance
  serialization unchanged — the durable repository adds physical
  serialization of file appends underneath it, not a replacement for it;
- switch production composition from
  `InMemoryStrategyInstanceRuntimeStateRepository` to
  `JsonlStrategyInstanceRuntimeStateRepository`; keep the in-memory
  implementation for tests and other explicitly ephemeral compositions;
- add `RUNTIME_STATE_PATH` configuration — a file path, e.g.
  `/runtime/state/runtime_state.jsonl`, not a mount directory — and a third
  writable Docker mount *directory*, `/runtime/state`, sourced from host
  directory `${BBB_DATA_ROOT}/strategy-runtime/state`, symmetric with how
  `RUNTIME_JOURNAL_PATH=/runtime/journal/runtime.jsonl` names a file inside
  the existing `/runtime/journal` mount; alongside the existing read-only
  specs mount, compatible with a read-only container root filesystem;
- scope V1 to a single Runtime process/writer, with no distributed
  coordination, compare-and-swap, or multi-replica contract;
- scope V1 to append-only growth, with no rotation, compaction, or retention;
- ship first rollout against clean operational state (flat exchange, no
  active trade cycles); no migration of existing in-memory state into the new
  file.

## Capabilities

### New Capabilities

- `runtime-durable-state-store`: File-backed, fsync-durable, replay-recovered
  storage for `StrategyInstanceRuntimeState`, keyed by `strategy_instance_id`
  in one shared append-only JSONL file.

### Modified Capabilities

- `runtime-production-composition`: production composition selects the
  durable file-backed repository instead of the in-memory repository. The
  existing "Non-durable Live V1 limitation is accepted, not open"
  requirement no longer holds as written for strategy-instance state, so it
  is removed and replaced — via REMOVED + ADDED, since narrowing it in
  place would force-keep or silently drop scenario names whose asserted
  outcome this change makes false — by a requirement scoping that
  acceptance to the committed-bar intake queue only, plus a new requirement
  gating `ready=True` on successful durable-state replay.
- `strategy-runtime-docker`: adds the third writable `/runtime/state` mount
  directory (sourced from `${BBB_DATA_ROOT}/strategy-runtime/state`),
  backing `RUNTIME_STATE_PATH=/runtime/state/runtime_state.jsonl`; removes
  the existing "state remains non-durable, lost on restart" claim, which
  this change makes false; renames the requirement whose title claimed "one
  writable journal mount, no other writable path" — via REMOVED + ADDED,
  since the rename also changes its body — to a title that accounts for the
  new writable state mount.

## Impact

- New repository implementation under
  `src/strategy_runtime/infrastructure/runtime_state/`.
- `src/strategy_runtime/config/model.py`, `loader.py`, `startup.py`: add
  `RUNTIME_STATE_PATH` following the existing `RUNTIME_JOURNAL_PATH` pattern.
- `src/strategy_runtime/bootstrap/application.py`: construct and wire the
  durable repository in place of the in-memory one; run startup replay before
  readiness.
- `docker-compose.yml`, `Dockerfile`, `README.md`: third bind mount and
  documented `docker run`/Compose invocation.
- No change to `StrategyInstanceRuntimeStateRepository`'s port contract, to
  `StrategyInstanceKeyedMutexRegistry`, to `StrategyInstanceRuntimeState`'s
  shape, to `processing_journal`, to the ABI/Engine/webhook contracts, or to
  `CommittedBarIntakeBoundary` durability.
