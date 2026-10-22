## 1. strategy_runtime

- [ ] 1.1 Atomic single-field writer per D4: instance file lookup from the catalog snapshot, parse like the catalog, replace only `enabled`, identity check, hidden temporary file in the same directory, `fsync`, mode kept, hash comparison before `os.replace`, directory `fsync`.
- [ ] 1.2 `StrategyEnabledControlService` per D2 and D3: mutex with a 30 s wait, state get-or-create, decision table, corrective CANCEL with the exact-absence rule, file written last.
- [ ] 1.3 `PUT /v1/strategy-instances/{id}/enabled` in the HTTP app with the status codes and reasons of the spec; production composition wires the writer, the service, the resolver and the ABI recovery adapter. `docker-compose.yml` of strategy_runtime: specs mount writable.
- [ ] 1.4 Tests:
  - decision table: no cycle, position open, recovery pending (entry and close), closure detected, entry order cancelled, cancel not confirmed, ABI error, instance busy; every non-200 leaves state and file byte-identical;
  - writer: only `enabled` changes, other keys and order kept, identity unchanged, temporary file never visible to the catalog and removed on failure, file changed since read refused, mode kept, write failure gives 500 and the old file stays whole;
  - enable and already-in-state make no ABI call and no write; unknown id 404; duplicate or invalid file refused; bad bodies 422; not ready 503;
  - the next catalog read after a change selects or skips the instance accordingly; existing list and selection behaviour unchanged.
- [ ] 1.5 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy`, `openspec validate --all --strict` green.

## 2. Mac smoke (before apply is allowed, owner's word for the Mac session)

- [ ] 2.1 On a copy of the specs directory mounted like production: `os.replace` of one file succeeds; Runtime's next catalog read shows the new `enabled`; Research reads the same value; file mode and ownership recorded; the temporary file is not listed as a deployment.
- [ ] 2.2 Result recorded here and shown to the owner.

## 3. Rollout (on owner's word only)

- [ ] 3.1 PR, merge, deploy only on the owner's word; bbb_stack mount change is a separate PR.
- [ ] 3.2 On the Mac demo: disable an idle strategy; disable one with an entry order and see the order cancelled on Bybit; try to disable one with an open position and get `position_open`.
