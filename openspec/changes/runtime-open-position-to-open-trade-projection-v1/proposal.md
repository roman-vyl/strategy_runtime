## Why

`runtime-abi-open-position-trade-cycle-alignment-v1` left `position_open=true`
fail-closed with `OpenTradeContextUnavailable` as a temporary boundary,
before any Engine call. Runtime now has everything needed to go further: an
in-memory `CurrentTradeCycle`, the first-fill transition
(`apply_first_fill`), and a fully specified `StrategyEngineOpenTradePort`
HTTP adapter. This change wires those existing pieces together so an open
position reaches Strategy Engine's open-trade endpoint.

Cold-restart recovery, lost-`CurrentTradeCycle` search, and reconciliation
after a crash are out of scope for V1 (in-memory-only Runtime state); this
change only handles a position whose `CurrentTradeCycle` already exists in
the live process.

## What Changes

- **BREAKING** `StrategyRuntimeOrchestrator.process(...)` freezes the
  first-fill context (via the existing `apply_first_fill`) and saves it
  before routing, whenever `resolved.position_open` is `true` and the
  current trade cycle is not yet frozen. Freeze failures
  (`FirstFillInvariantError`) propagate before the router is called.
- **BREAKING** `StrategyUseCaseRouter` no longer raises
  `OpenTradeContextUnavailable` unconditionally for `position_open=true`. It
  now requires a frozen entry context on the resolved runtime state's
  current trade cycle (raising `OpenTradeContextUnavailable` only if one is
  missing), builds `OpenTradeProjectionRequest` from the registered spec
  snapshot and the frozen context, calls
  `StrategyEngineOpenTradePort.project_open_trade(...)`, and returns a real
  `OpenTradeProjectedStrategyInstance`.
- No change to the ABI open-position client, the Strategy Engine open-trade
  HTTP adapter/codec, or `StrategyRuntimeOrchestrator`'s existing
  `OpenTradeProjectionUnsupportedError` boundary for the returned
  projection — this change only makes that boundary reachable.
- `average_entry_price` is still never read for Engine mapping; only
  `first_fill_at_ms` reaches `apply_first_fill`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `use-case-router`: replace the unconditional open-trade fail-closed
  requirement with a frozen-context-conditional one: build and send
  `OpenTradeProjectionRequest`, return `OpenTradeProjectedStrategyInstance`
  when a frozen entry context exists; fail closed only when it doesn't.
- `strategy-runtime-orchestrator`: add the first-fill freeze-and-save step
  between position resolution and routing for an open position, ahead of
  the unchanged post-projection dispatch.

## Impact

- `src/strategy_runtime/runtime/routing/router.py`,
  `src/strategy_runtime/runtime/orchestrator/orchestrator.py`.
- Tests: `tests/unit/runtime/test_semantic_pipeline.py`,
  `tests/unit/runtime/orchestrator/test_closed_bar_runtime_orchestration.py`.
- No change to `runtime/open_position/*`, `infrastructure/abi/*`,
  `infrastructure/strategy_engine/*`, `bootstrap/application.py`, or any
  ABI/Engine contract.
- Out of scope: cold-restart recovery, lost-trade-cycle search, persistent
  repository, `average_entry_price` in the Engine contract, applying
  `desired_protection`/`close_signal`/diagnostics, stop/take amendment,
  close-position command, ABI position-management endpoint, closing
  `CurrentTradeCycle`.
