## 1. strategy_runtime

- [ ] 1.1 `EnabledOverrideStore` port and JSONL adapter per D1: append with fsync, replay at start (last line per instance wins, truncated final line dropped, corrupt line fails startup), configured next to the journal directory.
- [ ] 1.2 `apply_enabled_overrides(snapshot, overrides)` per D2; the bar path and `GET /v1/strategy-instances` use it; the selector is unchanged.
- [ ] 1.3 `StrategyEnabledControlService` per D3 to D5: mutex with a 30 s wait, state get-or-create, decision table, corrective CANCEL with the exact-absence rule, write order per D4.
- [ ] 1.4 `PUT /v1/strategy-instances/{id}/enabled` in the HTTP app with the status codes and reasons of the spec; production composition wires the store, the service, the resolver and the ABI recovery adapter.
- [ ] 1.5 Tests:
  - decision table: no cycle, position open, recovery pending (entry and close), closure detected, entry order cancelled, cancel not confirmed, ABI error, instance busy; every non-200 leaves state and override unchanged;
  - enable and already-in-state make no ABI call; unknown id 404; bad bodies 422; not ready 503;
  - override wins over the file in selection and in the list; override for a removed spec ignored;
  - store: restart keeps the value, truncated final line, corrupt line fails startup, write failure gives 500 and no change;
  - existing list and selection behaviour without overrides unchanged.
- [ ] 1.6 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy`, `openspec validate --all --strict` green.

## 2. Rollout (on owner's word only)

- [ ] 2.1 PR, merge, deploy only on the owner's word.
- [ ] 2.2 On the Mac demo: disable an idle strategy; disable one with an entry order and see the order cancelled on Bybit; try to disable one with an open position and get `position_open`.
