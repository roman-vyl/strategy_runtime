## 1. strategy_runtime

- [x] 1.1 Trash mover per D1 in `utility/deployment_catalog`: locate the file from the snapshot, hash check, hidden `.deleted/` created on demand, no-overwrite move (link then unlink), directory `fsync`, cleanup of the trash copy on failure.
- [x] 1.2 Shared cancel step: extract the "refuse on recovery, position or closure; cancel a resting entry order; clear the cycle" logic of `StrategyEnabledControlService` into one function used by both services; the enable and disable behaviour and tests stay unchanged.
- [x] 1.3 `StrategyDeleteService` per D3 and D4.
- [x] 1.4 `DELETE /v1/strategy-instances/{id}` in the HTTP app with the codes and reasons of the spec; production composition wires the service.
- [x] 1.5 Tests:
  - decision table: unknown id, enabled, recovery pending (entry and close), position open, closure detected, entry order cancelled, cancel not confirmed, ABI error, instance busy, no cycle; every refusal before the CANCEL leaves state and file byte-identical and the trash empty; after a confirmed CANCEL a `file_changed`, `trash_name_taken` or `move_failed` leaves the file in place and unchanged and the state with no cycle, and the retry makes no ABI call; the normal path (disabled through the route, no cycle) makes no ABI call;
  - mover: file lands in `.deleted/` with the timestamp name and the original bytes, top-level scan no longer lists it and does not list the directory, failure after the link removes the trash copy, file changed since read refused, trash name taken refused;
  - a second `DELETE` of the same id gives 404; the state record is unchanged; the next bar and list no longer contain the instance;
  - existing enable, list and selection tests unchanged.
- [x] 1.6 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy src`, `openspec validate --all --strict` green.

## 2. Mac smoke (before apply, owner's word for the Mac session)

- [ ] 2.1 On a copy of the specs directory on the bind mount, as the Runtime user: create `.deleted/`, link a file in, unlink the original; Runtime's and Research's scans do not list the file or the directory; moving the file back lists it again. Record the result here.

## 3. Rollout (on owner's word only)

- [ ] 3.1 PR, merge, deploy only on the owner's word. No compose change is needed.
- [ ] 3.2 On the Mac demo: delete a disabled idle strategy; delete a disabled one with an entry order and see the order cancelled on Bybit; try one with an open position and get `position_open`; try an enabled one and get `still_enabled`; put the file back from `.deleted/` and see it listed.
