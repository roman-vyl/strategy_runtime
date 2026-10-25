## 1. strategy_runtime

- [ ] 1.1 `entry_package_models.py`: `EntryPackageDeclined` (`strategy_instance_id`, `trade_cycle_id`, `decline_reason`, `decline_message`, `status = "entry_package_declined"`) with shape checks of D2; add it to `EntryPackageResult`.
- [ ] 1.2 `entry_package_codec.py`: decode the closed declined body; reject it for a request with `desired_entry: null`; same identity binding as the other success DTOs.
- [ ] 1.3 `entry_reconciliation/models.py`: `EntryDeclinedOutcome`; bridge maps `EntryPackageDeclined` to it.
- [ ] 1.4 `EntryReconciliationExecutionPort` return type `SuccessfulEntryConfirmation | EntryDeclinedOutcome`; orchestrator handles it as D3, D5, D6 (Apply and Replace paths); new `EntryDeclinedJournalPort`.
- [ ] 1.5 Journal: `ENTRY_PACKAGE_DECLINED` event type and `entry_package_declined(...)` in the JSONL adapter; production composition passes the journal to the orchestrator.
- [ ] 1.6 Tests: codec accepts a valid declined body; rejects missing or extra field, empty or badly shaped reason, empty message, mismatched ids, declined for a CANCEL request, non-200 declined; bridge mapping; orchestrator Apply declined (no cycle, marker durably null, one save after the marker save, journal event with the exact values, returned state), Replace with declined APPLY (cycle removed, marker null), declined at a CANCEL step is an invariant error, identity mismatch is an invariant error, journal failure absorbed; the next bar after a decline sends a new APPLY with a new id; all existing tests for applied, absent and errors unchanged.
- [ ] 1.7 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy src`, `openspec validate --all --strict`.

## 2. Rollout (on owner's word only)

- [ ] 2.1 PR and merge only on the owner's word.
- [ ] 2.2 Deploy before the ABI change. Check on the Mac demo that entries still apply and cancel as before (ABI does not send `declined` yet).
