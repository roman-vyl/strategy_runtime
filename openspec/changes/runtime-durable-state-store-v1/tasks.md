## 1. On-Disk Record Codec

- [x] 1.1 Add an encode function from `StrategyInstanceRuntimeState` (and its
      nested `RegisteredSpecSnapshot`, `CurrentTradeCycle`,
      `AppliedEntryPackage`, `FrozenExecutedEntryContext`, `DesiredEntry`,
      `DesiredProtection`) to one JSON-serializable envelope containing
      `schema_version` and `strategy_instance_id`.
- [x] 1.2 Add a matching decode function that reconstructs the aggregate
      through its existing frozen-dataclass constructors, so existing
      `__post_init__` validation runs on decode.
- [x] 1.3 Add a round-trip test: encode then decode reproduces an
      equivalent aggregate for a state with `current_trade_cycle = null`
      and for one with a populated `CurrentTradeCycle` including
      `frozen_entry_context` and `latest_confirmed_management_protection`.
- [x] 1.4 Decode SHALL reject any field outside the exact allowed key set
      for the envelope, `CurrentTradeCycle`, `AppliedEntryPackage`,
      `DesiredEntry`, `FrozenExecutedEntryContext`, and
      `DesiredProtection` — schema drift fails loudly instead of being
      silently dropped. `raw_spec`'s own internal keys stay unrestricted
      (opaque deployment content). Add tests for an extra top-level
      envelope field and an extra nested field (e.g. inside
      `current_trade_cycle` and inside `desired_entry`).
- [x] 1.5 Decode SHALL also require every nullable field's key to be
      present, reading it with `data["field"]` rather than
      `data.get("field")` — `current_trade_cycle`, `frozen_entry_context`,
      `latest_confirmed_management_protection`, and
      `DesiredProtection.take_price`. A record is a complete snapshot: an
      omitted key is a schema violation, not an implicit null; only an
      explicit JSON `null` decodes to `None`. Add tests for each field
      omitted (fails closed) and for each field explicitly `null`
      (decodes normally).

## 2. Durable Repository

- [x] 2.1 Add `JsonlStrategyInstanceRuntimeStateRepository` under
      `src/strategy_runtime/infrastructure/runtime_state/`, implementing
      `StrategyInstanceRuntimeStateRepository`
      (`get_or_create` / `get` / `save`) by delegating identity,
      registration, and not-found semantics to the same in-memory index
      logic `InMemoryStrategyInstanceRuntimeStateRepository` already uses.
- [x] 2.2 On `get_or_create` creation and on `save`, append one encoded
      line: write, flush, `os.fsync(fileno)`, then update the in-memory
      index — in that order — before returning.
- [x] 2.3 Guard the append-write-flush-fsync sequence and the in-memory
      index update with one internal lock shared across every
      `strategy_instance_id`, distinct from
      `StrategyInstanceKeyedMutexRegistry`.
- [x] 2.4 On any failure during serialize/append/flush/fsync, propagate the
      exception without updating the in-memory index.
- [x] 2.5 Poison the repository instance when the physical write step
      (open/write/flush/fsync) fails: every later `get_or_create`, `get`,
      and `save` call on that instance raises a typed poisoned-store
      error instead of continuing to serve from the in-memory index or
      attempting another physical write. A failure before the physical
      write (serialization) does not poison. Poisoning is instance-wide,
      not scoped to the `strategy_instance_id` whose write failed.
      Recovery is a process restart (a fresh instance replays the file),
      not an in-process unpoison operation.
- [x] 2.6 Add a test that fails the actual physical write path (e.g. a
      monkeypatched `os.fsync` raising), not just serialization, and
      asserts: the triggering call's exception propagates; every
      subsequent call on that instance raises the poisoned-store error;
      a separate test confirms a serialization-only failure does not
      poison and the repository keeps serving normally afterward.

## 3. Startup Replay and Integrity

- [x] 3.1 On construction, read the configured file line by line and
      populate the in-memory index with the latest valid record per
      `strategy_instance_id`; treat a missing or empty file as zero
      records, not an error.
- [x] 3.2 Raise a fail-closed replay error whenever any line other than the
      last line fails to parse as JSON.
- [x] 3.3 Raise a fail-closed replay error whenever any line — including
      the last line — parses as syntactically valid JSON but fails
      envelope/schema/domain validation. Syntactic validity never earns a
      line leniency for domain-invalid content, regardless of position.
- [x] 3.4 Tolerate exactly one case: the last line failing to parse as JSON
      at all — discard it (log the recovered truncated tail) and keep that
      key's last valid prior record, if any. A last line that parses as
      valid JSON is always subject to 3.3, never this leniency.
- [x] 3.5 Add tests: replay of a clean file with multiple keys and
      superseding records; replay of a file with a JSON-parse failure on a
      non-last line (fails closed); replay of a file with a JSON-parse
      failure only on the last line (tolerated, prior record kept); replay
      of a file whose last line is syntactically valid JSON but fails
      schema/domain validation (fails closed, not tolerated); replay of a
      file whose only line is a JSON-parse failure (tolerated, empty
      index).

## 4. Configuration

- [x] 4.1 Add `state_path: Path` to `RuntimeConfig`
      (`src/strategy_runtime/config/model.py`) with the same
      non-empty-path validation as `journal_path`, defaulting to
      `var/state/runtime_state.jsonl` (matching the existing
      `var/journal/runtime.jsonl` local-dev default).
- [x] 4.2 Read `RUNTIME_STATE_PATH` in `load_runtime_config`
      (`src/strategy_runtime/config/loader.py`), following the existing
      `RUNTIME_JOURNAL_PATH` default/validation pattern. `RUNTIME_STATE_PATH`
      is always a file path (e.g. `/runtime/state/runtime_state.jsonl` in
      the container), never the bare mount directory (`/runtime/state`).
- [x] 4.3 Add `prepare_state_path` in
      `src/strategy_runtime/config/startup.py`, mirroring
      `prepare_journal_path` (create parent directory, reject a non-file
      existing path, open once in append mode to prove writability).

## 5. Production Composition

- [x] 5.1 In `src/strategy_runtime/bootstrap/application.py`, construct
      `JsonlStrategyInstanceRuntimeStateRepository` from
      `config.state_path` in place of
      `InMemoryStrategyInstanceRuntimeStateRepository`, and pass that one
      instance everywhere the shared repository is currently wired.
- [x] 5.2 Call `prepare_state_path` and construct/replay the durable
      repository inside the same fail-closed startup sequence as the
      other required components; a replay integrity failure or an
      unusable `RUNTIME_STATE_PATH` SHALL make `build_application` report
      `ready=False`.
- [x] 5.3 Keep `InMemoryStrategyInstanceRuntimeStateRepository` available
      and unchanged for tests and other explicitly ephemeral
      compositions.

## 6. Docker and Documentation

- [x] 6.1 Add a third bind mount to `docker-compose.yml`: host directory
      `${BBB_DATA_ROOT}/strategy-runtime/state` → container mount target
      `/runtime/state`, writable; set the container's
      `RUNTIME_STATE_PATH=/runtime/state/runtime_state.jsonl` as the file
      path inside that mount — symmetric with
      `RUNTIME_JOURNAL_PATH=/runtime/journal/runtime.jsonl` inside the
      existing `/runtime/journal` mount.
- [x] 6.2 Update the README `## Docker` section's example `docker run` and
      Compose usage to include the `/runtime/state` mount
      (`${BBB_DATA_ROOT}/strategy-runtime/state` on the host) and
      `RUNTIME_STATE_PATH=/runtime/state/runtime_state.jsonl`, alongside
      the existing specs and journal mounts.
- [x] 6.3 Confirm the image and container still start correctly with
      `--read-only` and exactly three mounts (specs read-only; journal
      and state writable) — no other writable path required.

## 7. Verification

- [x] 7.1 Unit-test the durable repository directly: create, save,
      identity-conflict, registration-conflict, not-found — same
      semantics as the existing in-memory repository test suite, plus
      durability (state is present after a fresh repository instance is
      constructed against the same file).
- [x] 7.2 Test that production composition reports `ready=False` when
      replay hits a non-last JSON-parse failure or any schema/domain
      validation failure (including on the last line), and `ready=True`
      on a clean file, an absent file, or a file whose only problem is a
      JSON-parse failure on its last line.
- [x] 7.3 Test `docker compose config` (or equivalent) resolves the third
      mount's `source`/`target` correctly and still fails closed when
      `BBB_DATA_ROOT` is unset.
- [x] 7.4 Run the complete Runtime test suite and Python compilation
      checks.
- [x] 7.5 Run `ruff`, `mypy`, and strict OpenSpec CLI validation
      (`openspec validate runtime-durable-state-store-v1 --strict`).

## 8. Closed Contract Decisions

- [x] 8.1 No feature flag or runtime switch is added between the durable
      and in-memory repositories; production composition selects the
      durable implementation unconditionally.
- [x] 8.2 No migration of pre-existing in-memory state into the new file;
      first rollout targets clean operational state only.
- [x] 8.3 No compaction, rotation, or retention is implemented; the file
      grows append-only for V1.
- [x] 8.4 No multi-process coordination (lock file, PID guard,
      compare-and-swap) is added; V1 assumes exactly one writing Runtime
      process.
- [x] 8.5 `CommittedBarIntakeBoundary`/webhook/FIFO delivery, MDS
      catch-up, and `processing_journal` semantics are left unchanged and
      out of scope.
