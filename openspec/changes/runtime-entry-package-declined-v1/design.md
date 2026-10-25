## Context

Runtime calls ABI `PUT /v1/strategy-instances/{sid}/trade-cycles/{tcid}/entry-package` from `EntryReconciliationOrchestrator._execute_one`:

1. it durably saves `pending_entry_recovery = {trade_cycle_id}` (`orchestrator.py`, before the call);
2. the bridge (`entry_reconciliation_bridge/bridge.py`) sends one request and returns `EntryAppliedConfirmation | EntryAbsentConfirmation` or raises `EntryReconciliationExecutionError` (for every public error, timeout, network or protocol failure);
3. on success `apply_success_confirmation` returns the replacement state with the marker cleared, and the bar orchestrator (`runtime/orchestrator/orchestrator.py`) saves it if it differs from the source state;
4. on an exception the marker stays and `uncertain_exchange_state_resolver` asks ABI's recovery endpoint every 30 s; bars of that instance are skipped while the marker is set.

APPLY always carries a freshly minted `trade_cycle_id`. An `entry_package_absent` answer to an APPLY is an invariant error today.

## Decisions

- **D1 A success DTO, not an error code.** `entry_package_declined` is HTTP `200` with a closed body: `strategy_instance_id`, `trade_cycle_id`, `status`, `decline_reason`, `decline_message`. It means: ABI did not send anything to the exchange for this pair and the pair is durably closed on the ABI side (ABI change, its recovery answer for the pair is `terminal_without_fill`). Rejected: a new HTTP code or a new `error.code` (the bridge maps every public error to the recovery path, and error bodies carry no ownership identifiers to bind to the request).
- **D2 Reason is a code plus a text, opaque for Runtime.** `decline_reason` is a non-empty string of `[a-z0-9_]`, starting with a letter, at most 64 characters (ABI's list in its change, for example `insufficient_balance_for_minimum_quantity`). Runtime does not branch on the reason: it validates the shape, journals it, and treats every reason the same way. A new ABI reason needs no Runtime change. `decline_message` is a non-empty human-readable string (ABI puts the numbers there), journaled verbatim.
- **D3 APPLY only.** The codec accepts `entry_package_declined` only when the request had a non-null `desired_entry`; for a CANCEL (including the resolver's corrective CANCEL through the same port) it is `AbiEntryPackageProtocolError`, which keeps today's failure path. The orchestrator also raises `EntryReconciliationInvariantError` if a declined outcome ever reaches a CANCEL step.
- **D4 New outcome type beside the success union.** The bridge returns `EntryDeclinedOutcome` (in `entry_reconciliation/models.py`). The port's return type becomes `SuccessfulEntryConfirmation | EntryDeclinedOutcome`. `apply_success_confirmation` is not called for it and stays unchanged. Rejected: reusing `EntryAbsentConfirmation` (it would lose the reason and hide the difference between "cancelled" and "refused").
- **D5 The orchestrator saves the cleared state itself.** On a declined APPLY the orchestrator checks the identity (`strategy_instance_id` and `trade_cycle_id` equal the sent command), saves `replace(pending_state, pending_entry_recovery=None)` through the repository, journals, and returns the saved state. It must save itself: for a plain APPLY the returned state equals the bar's source state, and the bar orchestrator skips the save when the states are equal, which would otherwise leave the marker on disk. For a Replace (confirmed CANCEL, then APPLY declined) the result is "no cycle, no marker"; the extra save by the bar orchestrator is harmless.
- **D6 Journal after the save.** `entry_package_declined` is written after the durable save, best effort like every journal event (a journal failure is absorbed and does not change state). Payload: `trade_cycle_id`, `bar_open_time_ms`, `risk_multiplier` (from the source state, the value that was sent), `decline_reason`, `decline_message`. Severity `warning`. Envelope and `schema_version` unchanged.
- **D7 Next bars as usual.** No retry inside the bar, no cooldown, no memory of the refusal. If the strategy still has a desired entry on the next bar, the normal APPLY path runs with a new identity and ABI decides again (the balance may have changed). Rejected: a cooldown (that would be a trading decision, and the owner kept those out of this step).

## Lost response

If the declined answer is lost (timeout, connection drop), Runtime cannot tell it from any other failure: the marker stays, the resolver asks ABI, ABI answers `terminal_without_fill` for the closed pair, and the resolver clears the marker (existing behavior, `resolver.py`). No new code is needed for this case.

## Risks

- A strategy whose entries are always refused (for example a balance too small for the exchange minimum) writes one `entry_package_declined` warning per bar while its desired entry lasts. This is intended: the journal shows why there are no trades.
- Central Journal reads `runtime.jsonl`. A new event type must not break its reader; check during review that an unknown `event_type` is skipped there (no change planned in this step).
