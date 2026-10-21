## 1. strategy_runtime

- [ ] 1.1 `EnabledOverrideStore` port and JSONL adapter per D1: append with fsync, replay at start (last line per instance wins, truncated final line dropped, corrupt line fails startup), configured next to the journal directory.
- [ ] 1.2 `apply_enabled_store(snapshot, store)` per D2: seed-once on the bar path and the PUT route, read-only view on `GET /v1/strategy-instances`; the selector is unchanged.
- [ ] 1.3 `StrategyEnabledControlService` per D3 to D5: mutex with a 30 s wait, state get-or-create, decision table, corrective CANCEL with the exact-absence rule, write order per D4.
- [ ] 1.4 `PUT /v1/strategy-instances/{id}/enabled` in the HTTP app with the status codes and reasons of the spec; production composition wires the store, the service, the resolver and the ABI recovery adapter.
- [ ] 1.5 Tests:
  - decision table: no cycle, position open, recovery pending (entry and close), closure detected, entry order cancelled, cancel not confirmed, ABI error, instance busy; every non-200 leaves state and override unchanged;
  - enable and already-in-state make no ABI call; unknown id 404; bad bodies 422; not ready 503;
  - seeded once from the file at first sight; a later file edit changes nothing; list shows the file value for a not-yet-recorded id without writing; record for a removed spec ignored;
  - store: restart keeps the value, truncated final line, corrupt line fails startup, write failure gives 500 and no change;
  - existing list and selection behaviour without stored values unchanged.
- [ ] 1.6 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy`, `openspec validate --all --strict` green.

## 2. Rollout (on owner's word only)

- [ ] 2.1 PR, merge, deploy only on the owner's word.
- [ ] 2.2 On the Mac demo: disable an idle strategy; disable one with an entry order and see the order cancelled on Bybit; try to disable one with an open position and get `position_open`.
