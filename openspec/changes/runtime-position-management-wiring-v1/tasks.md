## 1. Outer Orchestrator Wiring

- [ ] 1.1 Add a required `position_management_orchestrator:
  PositionManagementOrchestrator` constructor parameter to
  `StrategyRuntimeOrchestrator`, stored alongside the existing
  `entry_reconciliation_orchestrator`.
- [ ] 1.2 Replace the `OpenTradeProjectedStrategyInstance` branch in
  `process(...)`: call `self._position_management_orchestrator.execute(
  projection)`, then apply the existing save-if-changed comparison
  (`resulting_state == source_state`) exactly as the live-entry branch
  already does.
- [ ] 1.3 Remove `OpenTradeProjectionUnsupportedError` and its now-dead
  `raise` from `orchestrator/errors.py` and `orchestrator/orchestrator.py`.

## 2. Configuration

- [ ] 2.1 Add `RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS` to
  `RuntimeConfig` (`config/model.py`) and `load_runtime_config`
  (`config/loader.py`), following the exact
  `abi_open_position_timeout_seconds`/`abi_entry_package_timeout_seconds`
  pattern (required float, no default fallback).
- [ ] 2.2 Add the new variable to `config/runtime.env.example`.

## 3. Production Composition

- [ ] 3.1 In `build_application`, construct
  `HttpxAbiPositionManagementAdapter(base_url=config.abi_base_url,
  timeout_seconds=config.abi_position_management_timeout_seconds)` through
  `lifecycle.add(...)`, alongside the other four outbound clients.
- [ ] 3.2 Construct `PositionManagementOrchestrator(execution_port=
  position_management_client)` and pass it into
  `StrategyRuntimeOrchestrator(...)` as
  `position_management_orchestrator=...`.
- [ ] 3.3 Update the `_OutboundHttpClientLifecycle`/docstring references to
  "four outbound HTTP clients" (in `application.py`'s module and function
  docstrings) to "five".

## 4. Test Updates

- [ ] 4.1 Update every `StrategyRuntimeOrchestrator(...)` construction
  site (unit orchestrator tests, production e2e test) to pass a
  `position_management_orchestrator`.
- [ ] 4.2 Replace the existing `OpenTradeProjectionUnsupportedError`
  assertions in `tests/unit/runtime/orchestrator/
  test_closed_bar_runtime_orchestration.py` with per-decision coverage of
  the wired open-trade branch, mirroring the live-entry branch's existing
  coverage shape:
  - `NoOp` (no protection/close signal): `process(...)` returns the
    unchanged source state; repository `save(...)` is not called beyond
    any already-completed first-fill freeze save.
  - `ApplyProtection`: `PositionManagementOrchestrator.execute(...)`
    returns a state carrying a verified `ProtectionAppliedConfirmation`;
    that state is saved exactly once; the saved state is returned.
  - `ClosePosition`: same shape as `ApplyProtection`, with a verified
    `PositionClosedConfirmation` clearing `current_trade_cycle`.
  - A `PositionManagementOrchestrator.execute(...)` failure (standing in
    for any `PositionManagementExecutionError` from the execution port)
    propagates out of `process(...)` with no post-projection save, while
    an already-completed first-fill freeze save from earlier in the same
    invocation is preserved, not reverted or repeated — the direct
    regression test for the corrected "Persist no partial replacement on
    error" / "Propagate position-management failure" scenarios.
  - The nested `PositionManagementOrchestrator` receives no repository or
    mutex (construction-signature check, mirroring the existing
    `EntryReconciliationOrchestrator` check).
- [ ] 4.3 Update `tests/integration/committed_bar/test_production_e2e.py`
  to exercise the now-wired open-trade branch end to end for at least one
  `NoOp`, one `ApplyProtection`, and one `ClosePosition` cycle, including
  the freeze-persists-through-later-failure case from 4.2 at the
  production-composition level.
- [ ] 4.4 Update `tests/unit/bootstrap/test_composition_root.py`'s "four
  clients" assertions (construction count, shutdown-close count, startup
  rollback, `RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS` gating, and
  the intake-worker shutdown-sequence test's client-count assertion) to
  five, mirroring the existing per-client test shape for each of the
  other four.

## 5. Verification (this proposal pass)

- [x] 5.1 `npm exec -- openspec validate
  runtime-position-management-wiring-v1 --strict` passes.
- [x] 5.2 `npm exec -- openspec validate --all --strict` passes with no
  regression to any existing spec or change.
- [x] 5.3 Confirmed no production or test code was modified — only files
  under `openspec/changes/runtime-position-management-wiring-v1/` were
  added.
