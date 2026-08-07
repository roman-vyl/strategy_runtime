## Why

`StrategyRuntimeOrchestrator`'s open-trade branch still raises
`OpenTradeProjectionUnsupportedError`. Everything it needs to stop doing
that already exists and is ratified: `PositionManagementOrchestrator`
(`NoOp`/`ApplyProtection`/`ClosePosition` → command → execution port →
verified confirmation → aggregate) and its HTTP implementation of
`PositionManagementExecutionPort`, `HttpxAbiPositionManagementAdapter`. The
live-entry branch already wires the equivalent live-entry pair
(`EntryReconciliationOrchestrator` behind the same outer orchestrator, the
same save-if-changed rule) end to end. The only missing piece is the
symmetric wire for the open-trade branch, plus its production composition.

## What Changes

- `StrategyRuntimeOrchestrator` gains a `position_management_orchestrator`
  collaborator and, for an exact `OpenTradeProjectedStrategyInstance`,
  calls `PositionManagementOrchestrator.execute(projection)` inside the
  already-held keyed critical section, then applies the existing
  save-if-changed rule — mirroring the live-entry branch exactly.
  `OpenTradeProjectionUnsupportedError` and the "explicitly unsupported"
  behavior are retired.
- Production composition constructs `HttpxAbiPositionManagementAdapter` (a
  fifth outbound HTTP client, sharing `RUNTIME_ABI_BASE_URL` with its own
  new `RUNTIME_ABI_POSITION_MANAGEMENT_TIMEOUT_SECONDS`) and
  `PositionManagementOrchestrator`, wires the latter into
  `StrategyRuntimeOrchestrator`, and folds the new client into the
  existing single lifecycle owner (construct-once, close-once via rollback
  or shutdown) and the existing fail-closed configuration gate.
- The nested `PositionManagementOrchestrator` receives no repository and
  no keyed-mutex registry, matching `EntryReconciliationOrchestrator`'s
  existing pattern: the outer orchestrator remains the sole owner of the
  critical section and of every save decision.

## Non-Goals

- No new top-level orchestrator, decision, or state-transition logic.
- No retry, recovery, pending-command, or command-ID mechanism.
- No external-close lifecycle.
- No Strategy Engine or ABI contract change.
- No first-fill pipeline change.
- No MDS change.
- No unrelated refactor of already-ratified `PositionManagementOrchestrator`
  or `HttpxAbiPositionManagementAdapter` internals.

## Capabilities

### Modified Capabilities

- `strategy-runtime-orchestrator`: the open-trade branch becomes a
  supported, symmetric twin of the live-entry branch instead of an
  explicitly unsupported one.
- `runtime-production-composition`: the production graph gains a fifth
  outbound HTTP client and the constructed `PositionManagementOrchestrator`,
  under the same lifecycle and fail-closed configuration rules already
  governing the other four clients.

No new capability is introduced — `position-management-orchestrator` (the
nested orchestrator itself) and `abi-position-management-client` (its HTTP
implementation) are consumed exactly as already ratified and are not
modified by this change.

## Impact

- Touches `runtime/orchestrator/orchestrator.py`,
  `runtime/orchestrator/errors.py`, `bootstrap/application.py`,
  `config/loader.py`, `config/model.py`, and
  `config/runtime.env.example` at apply time — not part of this
  proposal-only pass.
- Existing tests asserting `OpenTradeProjectionUnsupportedError` (unit
  orchestrator tests, the production end-to-end test, and the composition
  "four clients" assertions) will need updating at apply time.
