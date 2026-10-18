## Why

When a cycle's own stop or take-profit fills on Bybit, Runtime has no way to end the cycle: the per-bar lookup gets `500` from ABI forever, and a `position_open: false` for a cycle with a frozen fill would raise in entry reconciliation. ABI's `abi-trade-cycle-closure-confirmation-v1` adds a proven `closure` (`stop_loss`, `take_profit`, `runtime_signal`) to the open-position and close responses. Runtime must accept it and connect it to the existing end-of-cycle transition, without a second close command and without bypassing `pending_close_recovery`.

## What Changes

- The open-position client accepts an optional `closure`; absent means `null`, so Runtime can ship before ABI.
- The per-bar orchestrator, right after the lookup and before routing, ends the cycle when `closure` is present: identity check, `current_trade_cycle = None`, durable save, then a `trade_cycle_closed` journal record. Engine is not called and no entry is placed on that bar.
- The close client accepts an optional `closure` in `trade_cycle_closed`; the existing confirmation path removes the cycle as today, and the closure is journaled after the save. This covers both a Runtime close and a stop or take-profit that beat Runtime's close while `pending_close_recovery` was set.
- New journal event `trade_cycle_closed`.
- No new state entity, no new command, no change to the pending-recovery protocol.

## Capabilities

### Modified Capabilities

- `abi-open-position-lookup-client`: `closure` in the success object.
- `open-position-resolver`: carries `closure` transiently.
- `strategy-runtime-orchestrator`: ends the cycle on a proven closure before routing.
- `abi-position-management-client`: `closure` in the close success object.
- `uncertain-exchange-state-resolver`: journals the closure after clearing `pending_close_recovery`.
- `processing-journal`: `trade_cycle_closed` event.

## Impact

`infrastructure/abi/open_position_codec.py`, `open_position/models.py`, `open_position/resolver.py`, `orchestrator/orchestrator.py`, `position_management_execution` (models, a second applier entry), `position_management_orchestrator`, `infrastructure/abi/position_management_codec.py`, `uncertain_exchange_state_resolver/resolver.py`, `utility/processing_journal`, tests. Journal service ingestion of `trade_cycle_closed` is a separate later change.
