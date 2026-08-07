## Why

`position-management-orchestrator` (archived
`runtime-position-management-execution-v1`) already ratified
`PositionManagementExecutionPort` — `apply_protection(ApplyProtectionCommand)
-> ProtectionAppliedConfirmation` and `close_position(ClosePositionCommand) ->
PositionClosedConfirmation` — and `PositionManagementOrchestrator` already
calls it. No implementation of this port exists yet, so Runtime cannot
actually apply protection or close a position through ABI.

The ABI wire contract this port must drive is already authoritative and
final: `abi_executor_bot`'s `docs/openapi/abi-position-management-api-v1.json`
defines `PUT .../protection` and `DELETE .../open-position` with closed
request/response schemas and fully enumerated error codes. Runtime already
has a proven HTTP-adapter philosophy for exactly this ABI-consumer shape
(`HttpxAbiOpenPositionLookupAdapter` / `open_position_codec.py`): strict
codec against the published contract, one bounded non-retried attempt, no
redirects, typed public/internal/protocol/timeout/network failures, and
cross-repository OpenAPI conformance verification.

This change adds only the missing HTTP implementation of the existing port,
following that existing philosophy exactly. No cross-source contradiction
was found between the port, the recipe models, and the authoritative ABI
OpenAPI document.

## What Changes

- Add one synchronous HTTP adapter implementing
  `PositionManagementExecutionPort` against ABI:
  - `apply_protection` issues `PUT
    /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/protection`
    with a closed `{stop_price, take_price}` body and returns
    `ProtectionAppliedConfirmation` only when the `200` response's
    `stop_price`/`take_price` exactly match the sent command.
  - `close_position` issues `DELETE
    /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position`
    with no request body and returns `PositionClosedConfirmation` only when
    the `200` response's identifiers match the sent command.
- Add a strict codec decoding only the closed success DTOs and the
  documented `400`/`415`/`422`/`500` error envelopes for each operation,
  per the authoritative OpenAPI document; every other status, content type,
  or malformed body is a protocol failure.
- Add typed failures distinguishing documented public ABI errors (including
  `422 position_not_open` from `apply_protection`, which surfaces as an
  ordinary typed execution error — no external-close handling is derived
  from it), `internal_error`, protocol failure, timeout, and network
  failure.
- One shared bounded timeout for the whole adapter; exactly one HTTP
  attempt per call, no retry, redirects disabled; opaque
  `strategy_instance_id`/`trade_cycle_id` path segments encoded the same
  way as the existing ABI open-position adapter.
- Add a cross-repository OpenAPI conformance test against
  `abi-position-management-api-v1.json`, mirroring the existing
  open-position/entry-package conformance tests.

## Non-Goals

- No production wiring (`bootstrap/application.py`, `create_http_app`, or
  any composition root change).
- No `StrategyRuntimeOrchestrator` or `PositionManagementOrchestrator`
  change.
- No state, repository, or mutex logic.
- No external-close lifecycle or reconciliation behavior.
- No retry, recovery, pending-state, or command-id mechanism.
- No ABI or Bybit change.
- No general HTTP-infrastructure refactor; this adapter follows the
  existing per-endpoint adapter pattern unchanged.

## Capabilities

### New Capabilities

- `abi-position-management-client`: The synchronous HTTP implementation of
  `PositionManagementExecutionPort` against ABI's `protection` and
  `open-position` endpoints — strict codec, bounded single attempt, typed
  failure classification, and cross-repository OpenAPI conformance.

### Modified Capabilities

None. `position-management-orchestrator` (the port, commands, and
confirmations) is consumed exactly as already ratified and is not changed.

## Impact

- New adapter and codec modules under the existing
  `infrastructure/abi/` HTTP-adapter area, plus their typed-error module,
  following the layout of the existing open-position/entry-package
  adapters.
- New contract tests (fake-ABI adapter tests and one cross-repository
  OpenAPI conformance test) under the existing `tests/contract/abi/` area.
- No change to any production wiring, orchestrator, state, or existing
  capability spec.
