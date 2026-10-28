## 1. Decision policy

- [ ] 1.1 Add pure `touch_trigger_entry_reconciliation(new_desired_entry, current_trade_cycle)` in `reconciliation.py` with the same type checks and `frozen_entry_context` fail-closed check as `decide_entry_reconciliation`; export it
- [ ] 1.2 Leave `decide_entry_reconciliation` unchanged

## 2. Orchestrator and composition

- [ ] 2.1 `EntryReconciliationOrchestrator(..., live_entry_mode="ema_anchor")`, validated; `execute` selects the decision function by mode; nothing after the decision changes
- [ ] 2.2 `bootstrap/application.py` passes `config.live_entry_mode` to `EntryReconciliationOrchestrator` only

## 3. Tests (targeted only)

- [ ] 3.1 Decision unit tests for `touch_trigger`: full table (no cycle × none/plan; acknowledged × none/equal/different), frozen-context raise, type errors
- [ ] 3.2 Orchestrator tests: `touch_trigger` with an acknowledged entry and a null or different projection → no id reservation, no command, no port call, no marker save, plan and `trade_cycle_id` unchanged; `touch_trigger` first entry → `Apply` as today
- [ ] 3.3 Same inputs with `ema_anchor` (and with the default) → `Cancel` and `Replace` as today
- [ ] 3.4 Invalid mode at orchestrator construction → error; bootstrap passes the configured mode
- [ ] 3.5 Existing targeted entry-reconciliation, orchestrator and bootstrap tests green; ruff and mypy clean
