## Why

Strategy Runtime calls Strategy Engine `live-entry` on every committed bar for every
enabled flat strategy instance, but the returned `desired_entry` is used for entry
reconciliation and then dropped. A `null` answer leaves no trace at all. There is no
history of what each live strategy wanted on each bar.

Runtime is the service that knows what Engine answered, for which strategy and which
bar, so Runtime itself states that fact. This change is deliberately small: Runtime
records the result of every successful `live-entry` evaluation, including
`desired_entry = null`, as a self-contained event in its own processing journal.
Nothing else.

## What Changes

- After every successful Engine `live-entry` response, Runtime appends one
  `live_entry_evaluated` event to its processing journal (`journal/runtime.jsonl`).
  The event carries `strategy_instance_id`, instrument, timeframe,
  `bar_open_time_ms` (the evaluated target bar) and `desired_entry` exactly as
  decoded (object or `null`). The event is written before entry reconciliation, so
  it is recorded even if the later ABI step fails.
- Processing journal appends become `fsync`-backed. The journal stays best effort:
  a write failure is counted and logged, never raised into orchestration.
- Journal envelope `schema_version` goes from 1 to 2.

## Out of Scope

Who reads the journal and how, ABI, trade cycles, open-trade /
managed evaluations, diagnostic snapshots and component events, frontend, read API,
marking an "effective" attempt among repeated evaluations of one bar, and any change
to Engine, to the durable state file or to trading logic.

## Capabilities

### Modified Capabilities

- `processing-journal`: new `live_entry_evaluated` event type; appends are
  `fsync`-backed; still best effort.

## Impact

- Runtime orchestrator or router, processing journal adapter and port, bootstrap
  wiring, tests.
- The durable state store (`state/runtime_state.jsonl`) and its schema are untouched.
- The event shape in design D3 is a published fact format: later changes may add
  fields but must not change the meaning of existing ones.
