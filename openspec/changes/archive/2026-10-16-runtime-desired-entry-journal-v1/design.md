## Context

Audit 2026-10-16 (thread "Trade Observatory"):

- Runtime routes a flat instance to `POST /v1/strategy-evaluations/live-entry` on
  every committed bar (`runtime/routing/router.py:49`). The response is decoded
  strictly into `desired_entry: DesiredEntry | None`
  (`LiveEntryProjectedStrategyInstance`, `runtime/routing/models.py:21`).
- The durable state file writes a line only when state changes
  (`runtime/orchestrator/orchestrator.py:93-95`), so it cannot carry per-bar
  observations, and its decoder is strict: a new field there would be a schema bump
  and would block rollback.
- The processing journal (`utility/processing_journal/jsonl_adapter.py`) already
  writes per-bar, per-instance events with `event_id` (uuid4), `occurred_at` and
  `strategy_instance_id`. It is append-only and best effort, but has no `fsync`.
- Runtime's intake queue accepts duplicate bars by design
  (`committed-bar-intake-queue` spec), so one bar can be evaluated more than once.

## Goals / Non-Goals

Goals: one durable observation per successful `live-entry` evaluation, `null`
included; zero effect on trading.

Non-goals: everything listed as out of scope in the proposal. Runtime produces
facts; how anyone consumes them is not part of this change.

## Decisions

### D1. Record in the processing journal, not in the state file

The processing journal is Runtime's existing observability log, is never read back by
Runtime, and is already best effort. Adding an event type there changes no trading
state, no replay and no rollback path. The state file stays as is.

### D2. Emit right after a successful Engine response

`RuntimeStrategyInstanceOrchestrator.process` (or the router) calls a new port
method `live_entry_evaluated(...)` immediately after `project_live_entry` returns and
before entry reconciliation. So the observation is recorded even when the following
ABI call fails, and is not recorded when Engine itself fails (that failure is already
journaled as `strategy_cycle_dispatch_failed`). Bars skipped because of a pending
recovery marker, and open-position bars, produce no `live_entry_evaluated` event.

### D3. Event shape

Envelope unchanged (`schema_version`, `event_id`, `event_type`, `occurred_at`,
`source`, `severity`, `strategy_instance_id`, `payload`, `diagnostics`), with
`event_type = "live_entry_evaluated"` and:

```json
"payload": {
  "instrument": "BTCUSDT",
  "timeframe": "5m",
  "bar_open_time_ms": 1786564200000,
  "desired_entry": null
}
```

or `desired_entry` with exactly the decoded fields: `side`,
`source_plan_bar_open_time_ms`, `planned_entry_price`, `initial_stop_price`,
`initial_take_price`, `locked_exit_profile`. Prices stay exact decimal text.
The journal envelope `schema_version` goes from 1 to 2 so readers can tell the
new event set apart; nothing in Runtime reads it.

### D4. fsync, still best effort

Each journal append does `flush` and `os.fsync`. Any failure is absorbed and counted
exactly as today. Cost is one fsync per event; at 5m bars this is negligible.

### D5. Producer guarantees

The event is self-contained: a reader needs no Runtime state, no Engine call and no
other line to understand it. Runtime appends only complete lines, each ending with a newline
character, and does not rotate or truncate the file in this change.

## Risks / Trade-offs

- Processing journal stays best effort: if a write fails, that observation is lost
  (counted in `failure_count`). Accepted: trading must not depend on it.
- The journal file keeps growing without rotation, as today. Rotation is a later
  change.
- Verification enables a real strategy instance. With the stack defaults ABI is
  `ABI_DRY_RUN=true` on testnet, but any non-null `desired_entry` still goes through
  entry reconciliation and the ABI call. The check must run with ABI in dry-run or
  demo mode, and with the 32 enabled `loadtest-*` specs handled first (owner's call).

