## 1. strategy_runtime

- [x] 1.1 Operator-commands service: close (checks, `enabled=false`, marker, ABI close, apply confirmation, journal, first-fill freeze) and cancel (existing cancel step, then `enabled=false`, runs when already disabled).
- [x] 1.2 Routes, response models and error mapping in the HTTP adapter; wiring in `bootstrap/application.py`.
- [x] 1.3 Tests: every scenario above with fakes for ABI; marker saved before the ABI call; no second close on repeat; no write on any refusal; 405.
- [x] 1.4 Targeted tests (`PYTHONPATH=src:.:tests`), `ruff`, `mypy`, `openspec validate --all --strict`.

## 2. Rollout (on owner's word only)

- [x] 2.1 PR, merge, deploy Runtime; smoke on Bybit demo: cancel an entry order, close a position, check the closure proof in the Journal.
