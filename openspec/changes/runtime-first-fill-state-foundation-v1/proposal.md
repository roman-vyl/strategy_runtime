## Why

`docs/system-plans/runtime-master-plan.md` (§6, line 257 and lines 280-287)
and `docs/system-plans/runtime-abi-entry-reconciliation-master-plan.md`
(§17, §19-21) reserve freezing the executed entry context on first fill as
future scope owned by `I5`. The implemented `I4a`/`I4b`/`I4c`/`I4d`
`CurrentTradeCycle` holds only `trade_cycle_id` and `applied_entry_package`.
`I5` (`docs/system-plans/runtime-abi-entry-delivery-map.md`,
`runtime-master-plan.md` lines 388/446/474/487) will provide HTTP webhook
handling, `AbiExecutionEventOrchestrator`, and production composition wiring
around a shared keyed mutex — but that orchestration has no pure domain logic
to call yet. Building orchestration and domain logic in one change conflates
ABI transport/HTTP concerns with a pure, independently testable operation
and makes `I5` itself large and hard to review.

This foundation closes that gap first: it gives `I5` exactly one pure
operation to call — "freeze the entry context on the first fill" — so `I5`
can stay a thin wiring layer (HTTP handler → orchestrator → mutex →
`repository.get()` → `apply_first_fill(...)` → `repository.save()` →
response) with no additional domain logic of its own.

## What Changes

- **BREAKING** Add a nullable `frozen_entry_context:
  FrozenExecutedEntryContext | null` field to `CurrentTradeCycle`, changing
  its previously exhaustive I2/I4a/I4b/I4c/I4d shape
  (`trade_cycle_id` + `applied_entry_package` only).
- Add `FrozenExecutedEntryContext` containing exactly `desired_entry`,
  `first_fill_at_ms`, and `entry_bar_open_time_ms`. Average execution price,
  filled/remaining quantity, any execution phase state machine, fill ledger,
  and any `EarlyExecutionObservation` remain explicitly out of scope for this
  change — scope deferred to the orchestration and fill-lifecycle layers.
- Add a pure helper `align_first_fill_to_entry_bar(first_fill_at_ms,
  base_timeframe) -> entry_bar_open_time_ms` that floors a fill timestamp to
  its containing candle's open time using a small, closed set of supported
  timeframe durations read only from
  `state.registered_spec_snapshot.base_timeframe` — never from an ABI event
  field.
- Add a pure state transition `apply_first_fill(state, trade_cycle_id,
  first_fill_at_ms) -> StrategyInstanceRuntimeState` that validates the
  current trade cycle and its identity, computes `entry_bar_open_time_ms`,
  copies the currently applied `DesiredEntry` unchanged, and returns a new
  immutable state with `frozen_entry_context` populated — first-call-wins,
  same-timestamp-retry is a no-op, and a conflicting retried timestamp fails
  closed with an invariant error.
- Add unit test coverage for the alignment helper and the transition,
  covering the full matrix in this change's `tasks.md`.

## Capabilities

### New Capabilities

- `first-fill-transition`: Defines the pure entry-bar alignment rule and the
  pure `apply_first_fill` state transition that freezes the executed entry
  context on the first ABI fill, including its idempotent-retry and
  fail-closed-conflict rules, entirely decoupled from ABI transport, HTTP,
  orchestration, and quantity/price lifecycle.

### Modified Capabilities

- `current-trade-cycle-state`: Replace the previously exhaustive
  I2/I4a/I4b `CurrentTradeCycle` shape with one that also carries an
  optional `frozen_entry_context: FrozenExecutedEntryContext | null`, and
  define the minimal pre-I5 `FrozenExecutedEntryContext` structure
  (`desired_entry`, `first_fill_at_ms`, `entry_bar_open_time_ms`) while
  still excluding phase, filled/remaining quantity, average execution
  price, and fill ledger from any current-cycle field.

## Impact

- Affected production code: `runtime/state/models.py` (extend
  `CurrentTradeCycle`, add `FrozenExecutedEntryContext`); new
  `runtime/first_fill/` package (`alignment.py`, `state_applier.py`,
  `errors.py`).
- Affected tests: `tests/unit/runtime/test_state_models.py` (extend); new
  `tests/unit/runtime/first_fill/` (`test_alignment.py`,
  `test_state_applier.py`).
- Explicitly out of scope, deferred to the future `I5` change
  (`runtime-abi-first-fill-orchestration-v1`): the HTTP first-fill
  callback endpoint, `AbiExecutionEventOrchestrator`, production
  composition wiring, any ABI webhook client, any change to ABI itself,
  any Engine open-trade call, outbox/retry/durable deduplication, and the
  filled/remaining quantity and average-price lifecycle.
- No change to `entry_reconciliation`, `entry_reconciliation_orchestrator`,
  `open_position` resolver, `routing/router.py`, the repository port/
  in-memory adapter's public contract, the keyed-mutex registry, or any
  ABI/Strategy Engine wire contract.
