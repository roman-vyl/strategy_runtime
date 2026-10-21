## Context

Audit of main `b084f9f` (Entry→Open audit, 2026-10-18). The Open Trade transition is `apply_first_fill`: it sets `frozen_entry_context` once per cycle and returns the same state object when the cycle is already frozen with the same `first_fill_at_ms`. It is saved in two places:

- A. bar path: `StrategyRuntimeOrchestrator._ensure_first_fill_frozen` (`orchestrator.py`), when `resolved.position_open` is true;
- C. recovery path: `UncertainExchangeStateResolver._resolve_uncertain_apply` (`resolver.py`), when ABI reports `position_open` for an Apply whose result was lost.

The uncertain-removal path with `position_open` only clears `pending_entry_recovery`; it does not freeze, so path A freezes on the next bar. Runtime writes no journal record at either transition today.

## Decisions

### D1. Contract: strict, no compatibility shape

Open-position success keys: `position_open`, `first_fill_at_ms`, `average_entry_price`, `closure`, `entry_order_link_id`, `entry_order_id`, exactly. Recovery-state success keys: `recovery_state`, `applied_entry_package`, `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id`, `entry_order_id`, exactly.

- Open (`position_open: true` / `recovery_state: position_open`): `entry_order_link_id` is a non-empty string; `entry_order_id` is a non-empty string or `null`.
- Every other success shape: both are `null`.
- Any other key set or value is a protocol error (`OpenPositionLookupProtocolError` / `AbiEntryCycleRecoveryProtocolError`).

The optional-`closure` tolerance of `runtime-trade-cycle-closure-v1` (D6) is not kept: ABI `35b4436` already sends `closure` always, and the owner ruled out compatibility shapes. When both changes are archived, the "accepts an optional closure" requirement is replaced by this change's six-key requirement.

`entry_order_id: null` means ABI's confirmed order row carried no exchange id. Runtime never substitutes another value (for example the `order_id` from `entry_package_applied`).

### D2. Transient carriage

`OpenPositionLookupResponse` and `PositionResolvedStrategyInstanceRuntimeState` gain `entry_order_link_id: str | None` and `entry_order_id: str | None` with the same open/closed invariants as D1. `PositionOpenRecoveryState` gains the same two fields (`entry_order_link_id: str`, `entry_order_id: str | None`). None of them is persisted in Runtime state or used in any decision.

### D3. Transition detection

The event is written only when `apply_first_fill` returned a new state (`resulting_state is not state`) and `save` of that state returned. A later lookup with `position_open: true` on an already frozen cycle returns the same state object, so no record is written. This makes the record one fact per cycle, not one per observation.

- A: in `_ensure_first_fill_frozen`, after `self._state_repository.save(resulting_state)`, journal with `bar_open_time_ms = unit.committed_bar.open_time_ms` and the resolved lookup's `average_entry_price` and identifiers. The method gains the bar time as a parameter.
- C: in `_resolve_uncertain_apply`, for `PositionOpenRecoveryState`, after `save(reconstructed)`, journal with `bar_open_time_ms = None` and the recovery response's values.
- `first_fill_at_ms` is the value just frozen into `frozen_entry_context`.
- `apply_first_fill` raising, or `save` raising, writes nothing.

### D4. Journal record

`trade_cycle_opened`, schema version 2, `strategy_instance_id` in the envelope, payload:

`{trade_cycle_id, bar_open_time_ms, first_fill_at_ms, average_entry_price, entry_order_link_id, entry_order_id}`

- Meaning: the first confirmed execution of the cycle's entry order, a partial one included.
- `average_entry_price` is ABI's average at the moment of that observation, not necessarily the final entry price.
- `bar_open_time_ms` is the committed bar on which Runtime made the transition, or `null` on the recovery path. It is not the exchange fill time.
- A new port `TradeCycleOpenedJournalPort` (next to `TradeCycleClosedJournalPort`) and a helper that is a no-op when the port is `None`. The JSONL adapter implements it with the existing best-effort `_record`.

### D5. Reliability

Existing best-effort JSONL journal: a write failure only increments the failure counter, never raises into orchestration, and never changes state. There is no retry and no outbox; a crash between the save and the write loses that record.

### Invariants kept

- No change to when a position counts as open, to order management, to `frozen_entry_context`, to recovery decisions or to the Open Trade Projection.
- The save precedes the record on both paths.
- The record is written at most once per cycle by Runtime's own transition logic.

## Risks

- Rollout: the new Runtime rejects the current ABI `35b4436` open-position and recovery bodies. The Runtime PR merges first; Runtime and ABI (`abi-open-position-entry-order-identity-v1`) are deployed together.
- A record lost to a journal failure or a crash right after the save is not recovered.
