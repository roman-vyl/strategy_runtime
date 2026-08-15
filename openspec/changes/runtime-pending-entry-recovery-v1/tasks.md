## 1. Domain model

- [ ] 1.1 Add `PendingEntryRecovery` (`trade_cycle_id: str`, `created_at_ms: int`) to
      `runtime/state/models.py`.
- [ ] 1.2 Add `pending_entry_recovery: PendingEntryRecovery | None` to
      `StrategyInstanceRuntimeState`.
- [ ] 1.3 Collapse `Replace` into `Cancel` in `runtime/entry_reconciliation/` (decision
      table, command construction, confirmation model, state applier, frozen-context
      fail-closed checks) — three-way `NoOp`/`Apply`/`Cancel`.
- [ ] 1.4 Remove `Replace`-specific handling from
      `entry_reconciliation_orchestrator/orchestrator.py`.

## 2. Durable persistence

- [ ] 2.1 Add `list_ids_with_pending_entry_mutation() -> tuple[str, ...]` to the
      `StrategyInstanceRuntimeStateRepository` protocol and both implementations
      (in-memory, JSONL) as an O(n) filter over the already-resident in-memory index.
- [ ] 2.2 Bump the durable codec to `schema_version = 2`: `pending_entry_recovery` becomes
      a required envelope key (`null` or `{trade_cycle_id, created_at_ms}`), decoded under
      the existing exact-key-set rule.
- [ ] 2.3 Decode `schema_version = 1` records as `pending_entry_recovery = None`; encode
      every new write as `schema_version = 2`. No file rewrite.

## 3. Save-before-call invariant

- [ ] 3.1 In `entry_reconciliation_orchestrator/orchestrator.py`, durably save
      `pending_entry_recovery = {trade_cycle_id, now_ms}` before invoking the execution
      port, for both `Apply` (using the freshly minted id) and `Cancel` (using the
      existing current-cycle id).
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
- [ ] 5.2 Decode the five `recovery_state` values and the conditional
      `applied_entry_package`/fill-fact fields per the ABI wire contract.
- [ ] 5.3 Add a client method for the one corrective action (resend CANCEL for the
      recovery-target trade cycle), reusing the existing entry-package client where
      possible rather than introducing a second write path.

## 6. `UncertainExchangeStateResolver`

- [ ] 6.1 Implement `attempt(strategy_instance_id)`: under
      `keyed_mutex_registry.hold(...)`, the Runtime-side 24h backstop check, the ABI
      recovery-state query, and the resolution table from design.md Decision 5.
- [ ] 6.2 Implement the background worker (own thread, `_State` enum, `start()`/
      `stop_once()`, bounded interval with backoff), modeled on
      `CommittedBarIntakeWorker`.
- [ ] 6.3 Each interval, enumerate pending instances via
      `list_ids_with_pending_entry_mutation()` and call `attempt(...)` for each,
      catching and logging per-instance failures without stopping the loop.
- [ ] 6.4 Log an operator-visible event (not a state mutation) when either horizon
      (Runtime backstop or ABI's `recovery_horizon_exceeded`) is reached.

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
- [ ] 8.4 Resolver: each of the five ABI recovery states, for both the uncertain-Apply and
      uncertain-Cancel cases, including the `entry_order_live`-while-removal-intended
      resend-CANCEL path.
- [ ] 8.5 Resolver: Runtime's own 24h backstop fires without an ABI call once exceeded,
      and never fires before ABI's own horizon would have applied.
- [ ] 8.6 Codec: `schema_version = 1` records decode with `pending_entry_recovery = None`;
      `schema_version = 2` records require the key; every new write is `schema_version = 2`.
- [ ] 8.7 Orchestrator guard: a committed bar for an instance with
      `pending_entry_recovery` set does not call the use-case router or Strategy Engine.

## 9. Verification

- [ ] 9.1 Run the full unit/integration/contract test suite.
- [ ] 9.2 Run strict OpenSpec validation (`npm exec -- openspec validate --all --strict`).
