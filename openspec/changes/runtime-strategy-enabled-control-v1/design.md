## Context

The catalog snapshot is read from the files on every committed bar and every list request; `enabled` is not part of `strategy_instance_id`; the selector keeps only `deployment.enabled` ones. Research creates files with `os.link` and never overwrites. The corrective CANCEL (`AbiEntryCycleRecoveryPort.cancel`, a `desired_entry: null` entry package) and the exact-absence rule already exist in `UncertainExchangeStateResolver`. The catalog ignores names starting with `.` and non-`.json` files, so a temporary file in the same directory is invisible to it.

## Decisions

- **D1 The deployment file is the only source of truth.** No store, no seed. Restart, bar selection, the list route and Research (`current.runtime.enabled`) all read the same file.
- **D2 Disable under the mutex, ABI is the truth.** The service takes `StrategyInstanceKeyedMutexRegistry.hold(id)` (waits for a bar in flight, up to 30 s, else `503 instance_busy`). It loads state (creating it from the catalog like the bar path if absent) and decides:
  1. `pending_entry_recovery` or `pending_close_recovery` set → `409 recovery_pending`.
  2. no `current_trade_cycle` → write the file, `200`.
  3. else `open_position_resolver.resolve(state)`:
     - `position_open` → `409 position_open`;
     - a detected closure → `409 cycle_not_settled`;
     - otherwise the entry is not a position: `cancel(...)`; exact `EntryPackageAbsent` for this instance and cycle → save state with `current_trade_cycle=None`, then write the file, `200` with `cancelled_entry_order: true`; any other answer → `409 cancel_not_confirmed`; an ABI client error → `502 abi_unavailable`. State and file are unchanged on every non-200.
- **D3 The file is written last.** Order for disable: checks, ABI cancel, state cleared, file. A disabled file means the instance is no longer selected, so a cancel could never be retried after it; therefore the file goes last. If the file write fails after the cycle was cleared, the strategy stays enabled with no order, the route answers `500`, and a retry is idempotent. Enable is a single file write, no ABI call.
- **D4 Atomic single-field write.** The writer (a small component beside the catalog adapter):
  1. locate the file of the instance from the same snapshot (one file per accepted id; an id with duplicates or an invalid file is `404`/`409`, never written);
  2. read bytes, parse like the catalog does, remember a hash of the bytes;
  3. build the new document: the same parsed object with only `enabled` replaced, other keys and their order kept (including `research_source`);
  4. recompute `strategy_instance_id` from the new document and require it equal to the requested id, else refuse (`500 identity_changed`, nothing written);
  5. write to a hidden temporary file in the same directory, `fsync`, copy mode from the original;
  6. re-read the original and compare the hash; changed → remove the temporary file and refuse (`409 file_changed`);
  7. `os.replace`, then `fsync` the directory (a failure there is logged only).
- **D5 Accepted residual race.** Between step 6 and step 7 a manual edit of the same file can be lost. V1 accepts this on the condition that Runtime is the only programmatic editor of existing deployment files and hand-editing during a switch is not supported as a concurrent operation. Research only creates other files.
- **D6 Mount and permissions.** The specs mount of Runtime becomes writable (`strategy_runtime` compose and, in a separate bbb_stack PR, the stack compose). The root filesystem stays read-only and no other path is added. The Runtime user must be allowed to create a file in that directory.
- **D7 Mac smoke before apply.** On the owner's Mac bind mount: an atomic `os.replace` of one file succeeds; Runtime then sees the new content on the next catalog read; Research still reads the same `enabled` through its own mount; file mode and ownership stay acceptable. Results are recorded in tasks before apply is allowed.
- **D8 Out of scope.** No journal event for the change (follow-up if wanted). A strategy switched off by hand-editing the file while holding an order is not handled here. Removing nothing from the file format.

## Risks

- A bug in the writer could damage a trading file; mitigated by temporary file + `fsync` + `os.replace`, identity check before replacing, and tests on every refusal.
- The residual race of D5.
- The cancel and the resolver call are synchronous inside one HTTP request; bounded by the existing ABI client timeouts.
