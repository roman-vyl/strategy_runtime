## Context

`strategy-enabled-control` already owns the decision table for a safe disable: mutex, state, open-position resolver, corrective CANCEL, exact-absence rule, file written last. The catalog (Runtime) and the export scan (Research) list only entries of the specs directory that are files, whose names do not start with `.` and end in `.json`; a subdirectory is never read. The specs mount is writable for Runtime. Research is create-only and treats a missing file as `present: false`, so a trashed candidate can be exported again (the file name is free).

## Decisions

- **D1 Trash, not erase.** The file moves to `<specs>/.deleted/<stem>.<YYYYMMDDTHHMMSSZ>.json`. The directory is created on first use. The move is a hard link into the trash followed by unlinking the original (a no-overwrite rename), then `fsync` of both directories. If the link succeeds and the unlink fails, the trash copy is removed again and the route answers `500 move_failed`; the strategy stays where it was.
- **D2 Only a disabled strategy.** The first check, before any ABI call, is the file's `enabled`; `true` gives `409 still_enabled`. The owner disables first (a separate, already safe operation), then deletes.
- **D3 Same checks as the disable, under the mutex.** The service takes `StrategyInstanceKeyedMutexRegistry.hold(id, timeout_seconds=30)`. Order:
  1. unknown id (not an accepted deployment) → `404 strategy_instance_not_found`, before the mutex, so no lock entry is created;
  2. `enabled` is true → `409 still_enabled`;
  3. pending entry or close recovery → `409 recovery_pending`;
  4. no current trade cycle → go to 6;
  5. the open-position resolver: position open → `409 position_open`; closure detected → `409 cycle_not_settled`; otherwise the corrective CANCEL, exact `EntryPackageAbsent` for this instance and cycle, else `409 cancel_not_confirmed`; an ABI client error → `502 abi_unavailable`; on `absent` the state is saved with `current_trade_cycle=None`;
  6. the file is moved to the trash.
  The cancel logic is reused from the enabled-control service (one shared function), not copied.
- **D4 File last, unchanged bytes.** Before the move the service re-reads the file and compares it with the bytes it read at the start; a difference gives `409 file_changed` and nothing moves. A failure of the move leaves state cleared of an order that no longer exists, which is safe, and a retry is idempotent.
- **D5 State and history stay.** The record in `runtime_state.jsonl` is not touched (the store is append-only and offers no delete). It is harmless: it has no recovery marker and no cycle, so the recovery workers skip it. If the same strategy is put back, it resumes from a clean cycle. Journal events are not touched.
- **D6 After the delete.** The next list request and the next bar no longer contain the instance; a repeated `DELETE` for the same id answers `404`. Research shows the candidate as not in Runtime.
- **D7 Mac smoke before apply.** On a copy of the specs directory on the owner's bind mount, as the Runtime user: create `.deleted/`, hard-link a file into it, unlink the original; Runtime's catalog scan and Research's scan no longer list it and do not list the subdirectory; a file moved back is listed again.
- **D8 Out of scope.** Erasing or listing the trash, a Journal event for the delete, deleting state records, deleting several strategies at once, deleting an enabled strategy in one step.

## Risks

- A wrong move could take a live strategy out of the catalog. Mitigated by D2 (only disabled), D3 (same checks and ABI truth), D4 (byte comparison, file last) and tests on every refusal.
- The trash grows; the owner cleans it by hand until a later change.
