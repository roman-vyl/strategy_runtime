## 1. strategy_runtime

- [x] 1.1 Atomic single-field writer per D4: instance file lookup from the catalog snapshot, parse like the catalog, replace only `enabled`, identity check, hidden temporary file in the same directory, `fsync`, original mode (not `0600`) and trailing newline kept, hash comparison before `os.replace`, directory `fsync`.
- [x] 1.2 `StrategyEnabledControlService` per D2 and D3: mutex with a 30 s wait, state get-or-create, decision table, corrective CANCEL with the exact-absence rule, file written last.
- [x] 1.3 `PUT /v1/strategy-instances/{id}/enabled` in the HTTP app with the status codes and reasons of the spec; production composition wires the writer, the service, the resolver and the ABI recovery adapter. `docker-compose.yml` of strategy_runtime: specs mount writable.
- [x] 1.4 Tests:
  - decision table: no cycle, position open, recovery pending (entry and close), closure detected, entry order cancelled, cancel not confirmed, ABI error, instance busy; every non-200 leaves state and file byte-identical;
  - writer: only `enabled` changes, other keys and order kept, identity unchanged, temporary file never visible to the catalog and removed on failure, file changed since read refused, mode kept, write failure gives 500 and the old file stays whole;
  - enable and already-in-state make no ABI call and no write; unknown id 404; duplicate or invalid file refused; bad bodies 400; not ready 503;
  - the next catalog read after a change selects or skips the instance accordingly; existing list and selection behaviour unchanged.
- [x] 1.5 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy`, `openspec validate --all --strict` green.

## 2. Mac smoke (before apply is allowed, owner's word for the Mac session)

- [x] 2.1 On a copy of the specs directory mounted like production: `os.replace` of one file succeeds; Runtime's next catalog read shows the new `enabled`; Research reads the same value; file mode and ownership recorded; the temporary file is not listed as a deployment.
- [x] 2.2 Result 2026-10-22: python:3.12-slim, uid 10001, copy of the specs directory on the same bind mount: writing a hidden temp file, `fsync`, `os.replace` and directory `fsync` work; a read-only mount and a second read-write mount both saw each new value after every replace (new inode each time); the hidden temp name is not in the catalog scan; findings: the replaced file became `0600` unless the mode is copied, and `json.dump` drops the trailing newline.

## 3. Rollout (on owner's word only)

- [ ] 3.1 PR, merge, deploy only on the owner's word; bbb_stack mount change is a separate PR.
- [ ] 3.2 On the Mac demo: disable an idle strategy; disable one with an entry order and see the order cancelled on Bybit; try to disable one with an open position and get `position_open`.
