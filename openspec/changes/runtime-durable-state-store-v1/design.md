## Context

`StrategyRuntimeOrchestrator` and `AbiExecutionEventOrchestrator` share one
`StrategyInstanceRuntimeStateRepository` instance
(`runtime-production-composition`). Today that instance is
`InMemoryStrategyInstanceRuntimeStateRepository`
(`src/strategy_runtime/runtime/state/repository.py`): an `RLock`-protected
`dict[str, StrategyInstanceRuntimeState]` with no physical persistence. Every
`get_or_create` / `get` / `save` call obeys the port contract in
`strategy-instance-runtime-state-repository` (already ratified, unchanged by
this design): `save` always replaces one complete registered aggregate,
never diffs or patches; identity and registration mismatches raise typed
errors; callers serialize per-instance writes through
`StrategyInstanceKeyedMutexRegistry` before calling the repository.

`JsonlProcessingJournal`
(`src/strategy_runtime/utility/processing_journal/jsonl_adapter.py`) already
shows the repository-adjacent pattern for an append-only JSONL file with a
per-write lock, but it is explicitly best-effort: a write failure is
swallowed and logged. The durable state store inverts that stance —
`save()` must not return successfully unless the record is physically on
disk — so it cannot reuse that adapter, only its file-handling shape.

`src/strategy_runtime/infrastructure/runtime_state/` already exists as an
empty package (`"""Package boundary."""`), left as the placement for this
future implementation.

## Goals / Non-Goals

**Goals:**

- Make `StrategyInstanceRuntimeState` survive process stop/restart/recreate
  through a file-backed `StrategyInstanceRuntimeStateRepository`
  implementation, with no change to the port contract or to
  `StrategyInstanceKeyedMutexRegistry`.
- Guarantee that a `save()` that returns successfully is already durable:
  serialize → append → flush → `fsync` → return.
- Recover the latest valid snapshot per `strategy_instance_id` from the file
  on startup, before Runtime reports ready.
- Fail closed on file corruption — a syntactically valid but schema/domain
  -invalid record always fails closed, regardless of position — except a
  syntactically truncated (unparsable) final line from a crash mid-append,
  which is discarded in favor of the prior snapshot.
- Wire the durable repository into production composition in place of the
  in-memory one; add `RUNTIME_STATE_PATH` and its Docker mount.
- Fail loudly, not silently, on schema drift: reject an unrecognized field
  in any persisted structure (except the deliberately free-form
  `raw_spec`) instead of dropping it during decode.
- Treat a physical write failure of ambiguous on-disk outcome as fatal to
  the repository instance, not merely to the one call that triggered it.

**Non-Goals:**

- Durable `CommittedBarIntakeBoundary`, webhook/FIFO delivery, redelivery of
  closed bars, or MDS catch-up.
- Any change to `processing_journal`'s best-effort semantics, or reusing it
  for state recovery.
- Compaction, rotation, retention, or bounding file growth.
- Multi-process/multi-replica coordination, compare-and-swap, distributed
  locks, or leader election.
- Migrating existing in-memory state into the new file at first rollout.
- Any change to `StrategyInstanceRuntimeStateRepository`'s port shape, to
  `StrategyInstanceRuntimeState`'s field shape, or to ABI/Engine/webhook
  contracts.

## Decisions

### One shared append-only JSONL file, keyed by `strategy_instance_id`

Every `save()` (and the first `get_or_create()` creation) appends one
complete JSON object for one `strategy_instance_id` as one line. All
strategy instances share one file at `RUNTIME_STATE_PATH`. There is no
per-instance file and no directory-of-files layout.

**Rationale:** matches the existing `RUNTIME_JOURNAL_PATH` / `JsonlProcessingJournal`
shape the codebase already uses for one append-only operational file, keeps
the Docker/Compose mount contract to one more bind mount instead of a
directory whose entry count grows with strategy count, and needs no
directory-listing step during replay.

**Alternative considered:** one file per `strategy_instance_id`. Rejected —
adds a directory-management concern (creation, cleanup semantics if an
instance is retired) that the append-only journal precedent does not need,
for no benefit at expected strategy-instance counts.

### Durability is synchronous and blocking inside `save()`

`save()` (and creation inside `get_or_create()`) performs, in order:
serialize the complete aggregate to one compact JSON line → `write()` the
line → `flush()` the buffered writer → `os.fsync(handle.fileno())` → return
the stored aggregate. No part of this sequence is deferred to a background
thread, batched, or buffered across calls. If any step raises, `save()`
propagates the exception and the in-memory index is not updated — the
caller must not treat the state as saved.

**Rationale:** the proposal's invariant is that a returned `save()` implies
the state a restart will replay. Buffering or async flushing would let a
caller observe a "successful" save that a crash immediately after could
still lose — silently reintroducing the exact gap this change closes.

**Alternative considered:** batch/periodic `fsync`. Rejected — trades
correctness for throughput this store does not need; per-cycle save
frequency is bounded by committed-bar cadence per strategy instance, not a
high-frequency write path.

### A physical write failure poisons the repository for the rest of its process life

`_append`'s physical step — open, `write`, `write` the newline, `flush`,
`os.fsync` — runs inside one `try`/`except` that records any exception it
raises as the repository's poison state before re-raising it unchanged to
the caller. Serialization (`encode_state_line`) runs *before* that block
and is not covered by it: a serialization failure propagates exactly as
before, does not poison, and leaves the repository free to keep serving.
Once poisoned, every later `get_or_create`, `get`, and `save` call —
including on a *different* `strategy_instance_id` than the one whose write
failed — immediately raises `StrategyInstanceStateStorePoisoned` instead
of touching the in-memory index or attempting another physical write.
There is no unpoison operation; recovery is restarting the process, which
constructs a fresh repository that replays the file from scratch.

**Rationale:** `write`, `flush`, and `fsync` can each fail after partially
succeeding — `write`/`flush` may have already handed bytes to the OS page
cache before `fsync` fails to persist them, and a later `fsync` retry (or a
later append) has no way to know whether that partial write is still
sitting at the end of the file or not. Continuing to serve `get`/`save`
from the in-memory index after that point would let the process keep
running on state whose most basic guarantee — "a successful `save()`
implies a restart will replay it" — this exact failure just broke, with no
signal to the caller that the guarantee is gone. Poisoning the whole
instance, not just failing the one call, is what makes that broken
guarantee visible instead of silently returning to normal-looking
operation on the next call.

**Alternative considered:** propagate the exception but leave the
repository otherwise usable (the original behavior). Rejected — this is
exactly the ambiguous-durability gap identified during review: a caller
that swallows or logs-and-continues past that one exception would keep
issuing `get`/`save` calls against a store no longer provably durable,
with nothing forcing acknowledgment of the failure.

**Alternative considered:** attempt to reopen/re-verify the file and
clear the poison automatically. Rejected — verifying that a prior partial
write did not corrupt the file's last line is exactly the replay
integrity check that already exists, and running it mid-process
(concurrently with further appends) is a materially different and riskier
problem than running it once at startup. A full process restart already
provides that verification for free through the existing replay path.

### A dedicated write lock serializes physical appends, separate from the keyed mutex

The repository holds one internal `threading.Lock` guarding the
open-append-write-flush-fsync sequence and the in-memory index update,
across all `strategy_instance_id` values. `StrategyInstanceKeyedMutexRegistry`
still serializes the business-level critical section per instance, as it
does today; this repository lock only serializes the physical file
operation once callers already hold that business-level lock (or, for
`get`/replay, once they only need read access).

**Rationale:** two different problems. The keyed registry stops two writers
from racing to decide the next state of one instance. The file lock stops
concurrent instances' otherwise-independent physical appends from
interleaving mid-line in one shared file. Removing either does not make the
other redundant — this mirrors the explicit distinction already drawn in
`strategy-instance-keyed-coordination`'s "Distinguish the repository lock"
scenario for the in-memory repository's own internal lock.

### In-memory index rebuilt at startup, then kept in sync on every save

On construction, the repository replays the full file once into the same
`dict[str, StrategyInstanceRuntimeState]` shape
`InMemoryStrategyInstanceRuntimeStateRepository` already uses, applying
"last valid record for a key wins." After startup, `get_or_create`, `get`,
and `save` read and mutate that in-memory index exactly as the in-memory
implementation does — including its existing identity-conflict,
registration-conflict, and not-found error semantics — with the file append
added as an effect of a successful `get_or_create` creation or `save`.

**Rationale:** reuses the already-ratified, already-tested in-process
semantics unchanged, so this change adds a durability layer underneath
proven logic instead of re-deriving get/save behavior. Every read after
startup is an in-memory lookup — no per-call file read.

### Replay validates every record; only a syntactically truncated last line is tolerated

Replay reads the file sequentially. A JSON parse failure on any line other
than the last aborts startup — Runtime does not reach `ready=True`. A JSON
parse failure on the last line only is tolerated: it is discarded (logged
as a recovered truncated tail) and replay proceeds using whatever prior
valid record that key already had. Separately, a line that parses as
syntactically valid JSON but fails domain/schema validation (the same
`StrategyInstanceRuntimeState`/`RegisteredSpecSnapshot`/`CurrentTradeCycle`
validation `__post_init__` already enforces) always aborts startup — this
holds for every line, including the last one; syntactic validity earns no
leniency for domain-invalid content.

**Rationale:** a crash mid-`write()` can only ever leave a partial *final*
line that fails to parse as JSON, because appends are sequential and each
prior append already completed its own `fsync`. A line that *does* parse as
valid JSON but fails domain validation is not explained by that failure
mode at all — its physical write did complete — so it is a real corruption
regardless of where in the file it appears, and must fail closed the same
as any other line.

**Alternative considered:** also tolerating a validation failure on the
last line (treating any last-line problem as a possible crash artifact).
Rejected — a crash mid-append cannot produce well-formed-but-invalid JSON;
that outcome indicates a genuine bug or external corruption, exactly what
fail-closed handling exists to catch. Widening tolerance to it would let a
real defect silently discard a saved state instead of surfacing it.

**Alternative considered:** best-effort replay that skips any bad line
anywhere in the file. Rejected — this is the exact lenient-journal-replay
behavior the proposal explicitly forbids for state recovery
("нельзя использовать lenient journal replay как state recovery").

### On-disk record shape

Each line is one JSON object: a small envelope (`schema_version`,
`strategy_instance_id`) around a full serialization of
`StrategyInstanceRuntimeState`, produced by one paired encode/decode
function for the aggregate and its nested value objects
(`RegisteredSpecSnapshot`, `CurrentTradeCycle`, `AppliedEntryPackage`,
`FrozenExecutedEntryContext`, `DesiredEntry`, `DesiredProtection`).
Decoding reconstructs these through their existing frozen-dataclass
constructors, so their existing `__post_init__` validation runs on every
replayed record for free — there is no separate recovery-side validation
path to keep in sync with the domain models.

Decoding additionally checks each of those structures' JSON object against
an exact set of allowed keys and rejects any unrecognized one as a
`StateRecordDecodeError` — the same fail-closed replay path a missing
field or a domain-invalid value already takes. The one deliberate
exception is `RegisteredSpecSnapshot.raw_spec`: it is opaque, free-form
deployment JSON by design (see `deployment-catalog`), so its own internal
keys are never restricted — only the four keys that carry it
(`instrument`, `base_timeframe`, `raw_spec`, `source_path`) are checked.

**Rationale:** keeps exactly one source of truth for what a valid
`StrategyInstanceRuntimeState` is — the dataclasses themselves — instead of
a parallel recovery schema that could drift from them. Silently ignoring
an unrecognized field would let schema drift (a renamed field, a field
dropped from encode but not decode, a hand-edited file) pass replay
unnoticed instead of failing loudly, which this correctness-critical store
cannot accept — a dropped field on replay is data loss with no error.

### Production composition swaps the repository, adds no new switch

`build_application` constructs `JsonlStrategyInstanceRuntimeStateRepository`
from `config.state_path`, replaying it during startup, and passes that one
instance everywhere `InMemoryStrategyInstanceRuntimeStateRepository` is
passed today — no new configuration flag chooses between implementations.
The in-memory implementation stays only as an explicit test/ephemeral
composition, not a production alternative. Replay failure (fail-closed
integrity violation, or an unwritable/unreadable `RUNTIME_STATE_PATH`)
makes composition report `ready=False`, the same fail-closed shape
`runtime-production-composition` already uses for every other required
component.

**Rationale:** avoids a redundant runtime toggle for a decision that is
made once, at the composition root, exactly like every other production
adapter selection in this codebase.

### Configuration and mount follow the existing journal pattern exactly

`RUNTIME_STATE_PATH` is added to `RuntimeConfig`, `load_runtime_config`, and
a new `prepare_state_path` startup function, mirroring
`journal_path`/`RUNTIME_JOURNAL_PATH`/`prepare_journal_path` field-for-field
(non-empty path, parent directory created, must identify a file, opened in
append mode once at startup to prove writability), with a local-dev default
of `var/state/runtime_state.jsonl` (matching the existing
`var/journal/runtime.jsonl` default).

`RUNTIME_STATE_PATH` names a *file*, not a mount directory — exactly like
`RUNTIME_JOURNAL_PATH=/runtime/journal/runtime.jsonl` already names a file
inside the `/runtime/journal` mount, not the mount itself. Docker/Compose
add a third writable bind mount *directory*, `/runtime/state`, sourced from
`${BBB_DATA_ROOT}/strategy-runtime/state`; the container's
`RUNTIME_STATE_PATH` is set to `/runtime/state/runtime_state.jsonl`, a file
inside that mount — alongside the existing read-only specs mount and
writable journal mount, still compatible with `--read-only` /
`read_only: true` on the container root filesystem.

**Rationale:** this is the only precedent in the codebase for "one
writable, persistent, host-mounted JSONL path," so reusing its exact shape
minimizes new surface area and keeps the three mounts symmetric in the
Compose file and README.

## Risks / Trade-offs

- **Unbounded file growth** (explicit V1 non-goal: no compaction) → accepted
  for V1; if size becomes an operational problem, compaction is designed
  separately with its own crash/atomic-replace semantics, per the proposal.
- **`fsync` adds latency to every `save()`** → accepted: correctness here is
  explicitly prioritized over throughput, and save frequency is bounded by
  committed-bar/first-fill cadence per instance, not a hot path.
- **A corrupted file blocks the entire process at startup** (fail-closed by
  design) → accepted as the correct behavior for a correctness-critical
  store; mitigated operationally by keeping `RUNTIME_STATE_PATH` on the same
  backed-up host storage as other BBB operational data.
- **Single-writer assumption is not enforced by the file format itself**
  (no lock file, no PID guard) → accepted for V1's single-process boundary;
  a second process writing the same file is a deployment error, not a
  case this store detects or corrects.
- **Decode/encode drift between the aggregate models and the on-disk record
  shape** → mitigated by decoding through the same frozen-dataclass
  constructors that already validate the in-memory aggregate, and by
  rejecting any unrecognized field per structure, so a future field
  addition or rename that isn't kept in sync between encode and decode
  fails replay loudly instead of silently dropping data.
- **A transient physical-write failure (e.g. a momentary `fsync` error)
  poisons the whole repository instance, not just that one call** →
  accepted trade-off: correctness over availability for a
  correctness-critical store. The cost is an unplanned process restart
  to recover, which the existing Live V1 topology (one process, one
  replica, no distributed coordination) already tolerates as an
  operational event; the alternative — continuing to serve after an
  unverified partial write — is the exact ambiguity this store exists to
  close.

## Migration Plan

- First rollout targets clean operational state only (flat exchange, no
  active Runtime trade cycles, no old conflicting ABI scopes), as stated in
  the proposal — no migration of existing in-memory state into the new file;
  `RUNTIME_STATE_PATH` starts as an empty/absent file and replay trivially
  succeeds with zero records.
- Deploying this change requires provisioning the third host mount
  (`${BBB_DATA_ROOT}/strategy-runtime/state`) alongside the existing two;
  Compose fails closed (as it already does for `BBB_DATA_ROOT`) if that
  variable is unset.
- Rollback is redeploying the previous image build (in-memory repository);
  no data migration back is needed since first rollout carries no
  pre-existing durable data. This is a deploy-time rollback, not a runtime
  feature flag — consistent with there being no in-process switch between
  implementations.

## Open Questions

None blocking. `schema_version` is included in the on-disk envelope so a
future format change has a documented seam, but designing that migration is
out of scope for V1.
