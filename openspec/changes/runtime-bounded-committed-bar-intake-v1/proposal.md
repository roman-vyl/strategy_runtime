# Proposal: Bounded Committed-Bar Intake v1

## Why

`POST /v1/webhooks/closed-bar` currently accepts a request and schedules
processing via `fastapi.BackgroundTasks.add_task(...)`. Runtime itself owns
no process-level queue, capacity bound, FIFO ordering guarantee, or
queue-full rejection path for that work — actual concurrency is whatever
Starlette/anyio's thread pool happens to allow, not a reviewed property of
Runtime's own design.

Market boundary timestamps (top of hour, four hours, midnight UTC) are
exactly when many independently configured MDS streams commit a candle
close within the same wall-clock second, producing a burst of
near-simultaneous `CommittedBarOrchestrator.process` calls whose
concurrency Runtime does not control, size, order, or reject against. The
existing `StrategyInstanceKeyedMutexRegistry` does not solve this: it
prevents two writers from corrupting the *same* strategy instance's
state, but does nothing to bound how many distinct `process` calls — each
doing its own catalog load, deployment selection, and multi-instance
fan-out — are simultaneously mid-flight before any per-instance mutex is
even acquired.

This change gives Runtime a bounded, best-effort intake of its own — not
durable delivery. Runtime's state repository is already non-durable in
Live V1 (an in-flight cycle is already an accepted loss on process
termination), so a durable queue in front of it would only add
persistence machinery whose guarantee stops at the queue boundary.

This is Runtime's side of a two-repository change: MDS owns whether/when
to notify and the outbound HTTP attempt (`mds-runtime-committed-bar
-webhook-v1`, proposed separately); Runtime owns accepting the request,
bounding how much is buffered, and controlling concurrency. This change
does not require the MDS side to land first.

## What Changes

- **MODIFIED** `http-closed-bar`: the webhook handler stops using
  `BackgroundTasks.add_task` and instead performs one bounded,
  non-blocking `put_nowait` onto a new intake boundary. Acceptance
  semantics (`200 accepted` means "queued," not "processed") and existing
  validation/not-ready behavior are unchanged. **BREAKING**: two new
  rejection cases — a full queue, and a request arriving after shutdown
  has begun — both reuse the existing `503 not_ready` wire response but
  are logged server-side with distinct reasons (`queue_full` vs.
  `intake_stopping`).
- **ADDED** `committed-bar-intake-queue`: a bounded FIFO intake boundary
  with exactly one consumer worker, queue-full/intake-stopping rejection
  logging, and per-event failure isolation.
- **MODIFIED** `runtime-production-composition`: the composition root
  constructs the intake boundary and its single worker exactly once,
  wires the worker to the existing (unmodified) `CommittedBarOrchestrator`,
  adds one new required configuration field
  (`RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY`), and sequences shutdown as
  stop-accepting → offloaded worker stop → outbound-client close.

## What Does Not Change

`CommittedBarOrchestrator.process` is called with the same signature and
semantics as today — only *what calls it* changes (a queue worker instead
of a `BackgroundTasks` callback). `StrategyRuntimeOrchestrator`,
`EntryReconciliationOrchestrator`, the ABI and Strategy Engine contracts,
`StrategyInstanceRuntimeState`, and `StrategyInstanceKeyedMutexRegistry`
are untouched. The first-fill endpoint keeps its synchronous HTTP
contract, calling `AbiExecutionEventOrchestrator.process` directly with no
queue, no new lock, and no serialization across strategy instances. No
transactional outbox, persisted event log, dead-letter queue, replay,
retry/backoff, configurable worker count, horizontal scaling, or
multi-process shared state is introduced.

## Non-goals / Accepted losses (Live V1)

- No durability: an accepted-but-unprocessed event is lost on process
  termination.
- No dedup at the queue: downstream idempotency (reconciliation NoOp,
  first-fill's already-frozen-cycle check, value-equality-gated save)
  already makes reprocessing a duplicate committed bar a safe no-op.
- No forced interruption or hard shutdown timeout: shutdown waits for one
  already-current event to finish; its network calls are bounded by
  existing outbound timeouts, its local work is not.
- No cross-process coordination: this is a single-process, process-local
  boundary, matching the existing Live V1 constraint already documented
  for the keyed-mutex registry.
- No Engine/ABI contract changes; no change to the first-fill HTTP
  contract; no new worker-count setting.

## Capabilities

- New: `committed-bar-intake-queue`.
- Modified: `http-closed-bar`, `runtime-production-composition`.

## Impact

- Affected: `adapters/http/app.py`, new `runtime/committed_bar_intake/`
  module, `config/model.py` / `config/loader.py`,
  `bootstrap/application.py`.
- Not affected: `utility/committed_bar/`, `runtime/orchestrator/`,
  `runtime/entry_reconciliation*/`, `runtime/abi_execution_event/`,
  `runtime/coordination/keyed_mutex.py`, `runtime/state/`,
  `infrastructure/strategy_engine/`, `infrastructure/abi/`.
- Wire contract: the request body is `instrument`/`timeframe`/
  `open_time_ms` (existing, unmodified `http-closed-bar` shape); this
  change does not require the MDS companion change to land first.
