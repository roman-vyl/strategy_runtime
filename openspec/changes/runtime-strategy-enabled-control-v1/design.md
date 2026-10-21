## Context

Runtime state (`StrategyInstanceRuntimeState`) is stored with strict, versioned envelopes. The catalog snapshot is read per bar and per list request; the selector keeps only `deployment.enabled` ones. The corrective CANCEL (`AbiEntryCycleRecoveryPort.cancel`, a `desired_entry: null` entry package) and the exact-absence rule already exist in `UncertainExchangeStateResolver`.

## Decisions

- **D1 Override store, not a state field.** A new field in the state envelope means schema v4 and touches the strict codec, replay and every state spec. Instead one append-only JSONL file, `enabled_overrides.jsonl`, in the Runtime journal directory (already writable; specs stay read-only). One line `{"strategy_instance_id", "enabled", "at_ms"}`; the last line per instance wins; replayed at start; a line that is not valid fails startup (same fail-closed stance as the state file, except a truncated final line is dropped). A save is flushed and fsynced before the route answers `200`.
- **D2 Effective value computed once.** `apply_enabled_overrides(snapshot, overrides)` returns a snapshot whose deployments carry the effective `enabled`. The bar path and the list route both use it; the selector is unchanged.
- **D3 Disable under the mutex, ABI is the truth.** The service takes `StrategyInstanceKeyedMutexRegistry.hold(id)` (waits for a bar in flight, up to 30 s, else `503 instance_busy`). It loads state (creating it from the catalog like the bar path if absent) and decides:
  1. `pending_entry_recovery` or `pending_close_recovery` set → `409 recovery_pending`.
  2. no `current_trade_cycle` → write override, `200`.
  3. else `open_position_resolver.resolve(state)`:
     - `position_open` → `409 position_open`;
     - a detected closure → `409 cycle_not_settled` (the next bar settles it; Runtime does not duplicate the closure path);
     - otherwise the entry is not a position: `cancel(...)`; exact `EntryPackageAbsent` for this instance and cycle → save state with `current_trade_cycle=None`, then write override, `200` with `cancelled_entry_order: true`; any other answer → `409 cancel_not_confirmed`; an ABI client error → `502 abi_unavailable`. State and override are unchanged on every non-200.
- **D4 Order of writes.** Cycle cleared first, override second, so a disabled strategy never keeps an order. If the override write fails after the cycle was cleared the strategy stays enabled with no order and the route answers `500`; a retry is idempotent.
- **D5 Enable is a pure write.** No ABI call. Enabling a strategy that is already effective-enabled is `200` without a write.
- **D6 Out of scope.** No journal event for the change (Central Journal ingests only whitelisted events; follow-up if wanted). A strategy switched off by hand-editing the file while holding an order is not handled here.

## Risks

- After the first switch via the route, editing `enabled` in the spec file no longer changes that strategy. The list shows the effective value, so this is visible.
- The cancel and the resolver call are synchronous inside one HTTP request; bounded by the existing ABI client timeouts.
