## 1. Domain model

- [ ] 1.1 Add `PendingEntryRecovery` (`trade_cycle_id: str` only, no timestamp) to
      `runtime/state/models.py`.
- [ ] 1.2 Add `pending_entry_recovery: PendingEntryRecovery | None` to
      `StrategyInstanceRuntimeState`.
- [ ] 1.3 Collapse `Replace` into `Cancel` in `runtime/entry_reconciliation/` (decision
      table, command construction, confirmation model, state applier, frozen-context
      fail-closed checks) — three-way `NoOp`/`Apply`/`Cancel`.
- [ ] 1.4 Remove `Replace`-specific handling from
      `entry_reconciliation_orchestrator/orchestrator.py`.

## 2. Durable persistence

- [ ] 2.1 Add `list_ids_with_pending_entry_recovery() -> tuple[str, ...]` to the
      `StrategyInstanceRuntimeStateRepository` protocol and both implementations
      (in-memory, JSONL) as an O(n) filter over the already-resident in-memory index.
- [ ] 2.2 Bump the durable codec to `schema_version = 2`: `pending_entry_recovery` becomes
      a required envelope key (`null` or `{trade_cycle_id}`), decoded under the existing
      exact-key-set rule.
- [ ] 2.3 Decode `schema_version = 1` records as `pending_entry_recovery = None`; encode
      every new write as `schema_version = 2`. No file rewrite.

## 3. Save-before-call invariant

- [ ] 3.1 In `entry_reconciliation_orchestrator/orchestrator.py`, durably save
      `pending_entry_recovery = {trade_cycle_id}` before invoking the execution port, for
      both `Apply` (using the freshly minted id) and `Cancel` (using the existing
      current-cycle id).
- [ ] 3.2 On a successful confirmation, clear `pending_entry_recovery` in the same
      transition that applies the confirmed outcome.
- [ ] 3.3 On an execution-port exception, leave `pending_entry_recovery` exactly as
      durably saved before the call; propagate the exception unchanged.

## 4. Orchestrator guard

- [ ] 4.1 In `StrategyRuntimeOrchestrator.process(...)`, immediately after `get_or_create`
      and **before** the open-position resolver is called, return the current state
      unchanged when `pending_entry_recovery is not None` — no open-position lookup (this
      is what caused the original BTC-class `500` lockup: an unresolved trade cycle's
      status makes ABI's open-position lookup fail closed), no use-case routing, no Engine
      call, no new entry decision.

## 5. ABI recovery-state client

- [ ] 5.1 Add a Runtime-side HTTP client for
      `GET /v1/strategy-instances/{id}/trade-cycles/{id}/recovery-state`, following the
      existing open-position lookup client's opaque-path-encoding and strict-decoding
      conventions.
- [ ] 5.2 Decode the four `recovery_state` values (`entry_order_live`, `position_open`,
      `terminal_without_fill`, `terminal_after_fill`) and the conditional
      `applied_entry_package`/fill-fact fields per the ABI wire contract. Decode ABI's
      safe-error response (returned both for a genuine query failure and for
      insufficient positive evidence) as a single typed failure — the two are
      indistinguishable to Runtime and are treated identically.
- [ ] 5.3 Decode ABI's `422 unknown_trade_cycle_binding` as its own typed public error,
      distinct from any `recovery_state` — the resolver treats it identically to a
      transport/availability failure (`pending_entry_recovery` untouched), never as
      evidence of `terminal_without_fill`. If ABI can safely prove absence for a missing
      binding, that must be expressed as one of ABI's own documented `recovery_state`
      values, not inferred by Runtime from the HTTP status.
- [ ] 5.4 Add a client method for the one corrective action (resend CANCEL for the
      recovery-target trade cycle), reusing the existing entry-package client where
      possible rather than introducing a second write path.

## 6. `UncertainExchangeStateResolver`

- [ ] 6.1 Implement `attempt(strategy_instance_id)`: under
      `keyed_mutex_registry.hold(...)`, the ABI recovery-state query, and the resolution
      table from design.md Decision 5. No horizon or age check of any kind.
- [ ] 6.2 Implement the background worker (own thread, `_State` enum, `start()`/
      `stop_once()`, fixed bounded polling interval, no adaptive/exponential backoff),
      modeled on `CommittedBarIntakeWorker`.
- [ ] 6.3 Each interval, enumerate pending instances via
      `list_ids_with_pending_entry_recovery()` and call `attempt(...)` for each,
      catching and logging per-instance failures without stopping the loop.
- [ ] 6.4 On any response other than the four positive `recovery_state` values (transport
      failure, availability failure, or ABI's inconclusive-evidence safe error), leave
      `pending_entry_recovery` untouched and do nothing further this tick — no logging or
      alerting mechanism is introduced by this change.

## 7. Bootstrap wiring

- [ ] 7.1 Construct the resolver and worker in `bootstrap/application.py` alongside
      `intake_worker`.
- [ ] 7.2 Start the resolver worker in `_lifespan` startup, alongside `intake_worker`.
- [ ] 7.3 Stop the resolver worker before closing HTTP clients in shutdown, alongside
      `intake_worker`.

## 8. Regression coverage

- [ ] 8.1 An ambiguous Apply durably preserves `pending_entry_recovery` and never loses
      the minted `trade_cycle_id` (the ETH-class regression).
- [ ] 8.2 An ambiguous Cancel (including a formerly-Replace-triggered one) durably
      preserves `pending_entry_recovery`; the bar path fails closed via the guard, not via
      an uncaught `500` (the BTC-class regression).
- [ ] 8.3 `decide_entry_reconciliation` never returns `Replace`; a changed desired entry
      returns `Cancel`.
- [ ] 8.4 Resolver: each of the four ABI recovery states, for both the uncertain-Apply and
      uncertain-Cancel cases, including the `entry_order_live`-while-removal-intended
      resend-CANCEL path.
- [ ] 8.5 Resolver: ABI's safe-error response (query failure or insufficient positive
      evidence) leaves `pending_entry_recovery` untouched and is retried on the next tick —
      no distinction is made between "ABI couldn't answer" and "ABI answered
      inconclusively."
- [ ] 8.6 Codec: `schema_version = 1` records decode with `pending_entry_recovery = None`;
      `schema_version = 2` records require the key; every new write is `schema_version = 2`.
- [ ] 8.7 Orchestrator guard: a committed bar for an instance with
      `pending_entry_recovery` set does not call the use-case router or Strategy Engine.
- [ ] 8.8 Resolver: ABI's `422 unknown_trade_cycle_binding` leaves `pending_entry_recovery`
      untouched — it is never treated as `terminal_without_fill`.
- [ ] 8.9 Resolver: an instance whose pending marker never receives a positive
      `recovery_state` remains blocked on the bar-path guard indefinitely across
      arbitrarily many resolution attempts — no attempt count or elapsed-time threshold
      changes this behavior.

## 9. Verification

- [ ] 9.1 Run the full unit/integration/contract test suite.
- [ ] 9.2 Run strict OpenSpec validation (`npm exec -- openspec validate --all --strict`).
