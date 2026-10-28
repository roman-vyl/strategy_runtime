## 1. strategy_runtime

- [ ] 1.1 Journal: `ENTRY_CYCLE_ENDED` event type, `entry_cycle_ended(...)` in the JSONL adapter, journal port.
- [ ] 1.2 Emit after the durable save in the four paths: confirmed CANCEL in the entry-reconciliation orchestrator, the enabled-control cancel step, resolver terminal-without-fill, resolver exact-absent corrective cancel; production composition wires the port.
- [ ] 1.3 Tests: one event with exact payload per path (reason, cycle id, bar or null); none for applied, closed-after-fill, marker-only change or failed removal; Replace emits `cancelled` then the existing applied event; journal failure absorbed.
- [ ] 1.4 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy src`, `openspec validate --all --strict`.

## 2. Rollout (on owner's word only)

- [ ] 2.1 PR and merge only on the owner's word; Journal change first, then Runtime.
