## Why

Runtime does not journal the moment a trade cycle becomes an Open Trade. The fact exists only inside the saved state (`frozen_entry_context`), so the Central Journal cannot show when and from which order a position was opened. ABI's `abi-open-position-entry-order-identity-v1` adds `entry_order_link_id` and `entry_order_id` to the open-position and recovery-state responses; Runtime must accept them under strict decoding and write one `trade_cycle_opened` record at the state transition.

## What Changes

- **BREAKING (contract):** the open-position and recovery-state clients require the two new keys on every success body, with strict per-state rules. Old ABI bodies without them are rejected. Runtime and ABI are deployed together.
- The resolved open-position state carries both identifiers transiently.
- New journal event `trade_cycle_opened`, written once per cycle, only after the durable save of the first-fill transition:
  - bar path in `orchestrator.py` (`_ensure_first_fill_frozen`), with the committed bar's `bar_open_time_ms`;
  - recovery path in `uncertain_exchange_state_resolver/resolver.py` (uncertain Apply resolved as `position_open`), with `bar_open_time_ms: null`.
- No change to the definition of an open position, order management, `frozen_entry_context`, recovery decisions or the Open Trade Projection.

## Capabilities

### Modified Capabilities

- `abi-open-position-lookup-client`: two required keys in the success object.
- `abi-entry-cycle-recovery-client`: two required keys in every recovery-state success object.
- `open-position-resolver`: carries the identifiers transiently.
- `strategy-runtime-orchestrator`: journals the bar-path transition after the save.
- `uncertain-exchange-state-resolver`: journals the recovery-path transition after the save.
- `processing-journal`: `trade_cycle_opened` event.

## Impact

`infrastructure/abi/open_position_codec.py`, `infrastructure/abi/entry_cycle_recovery_codec.py`, `runtime/open_position/models.py`, `runtime/open_position/resolver.py`, `runtime/abi/entry_cycle_recovery_models.py`, `runtime/orchestrator/orchestrator.py`, `runtime/uncertain_exchange_state_resolver/resolver.py`, a journal port, `utility/processing_journal` (event type and adapter), production composition, tests. Journal service ingestion of `trade_cycle_opened` is a separate later change.
