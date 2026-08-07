## Why

`position-management-orchestrator` (archived
`runtime-position-management-execution-v1`) already ratified
`PositionManagementExecutionPort` and calls it, but no HTTP implementation
exists — Runtime cannot yet apply protection or close a position through
ABI. `abi_executor_bot`'s `docs/openapi/abi-position-management-api-v1.json`
is the final authoritative wire contract for this. Runtime already has a
proven adapter philosophy for exactly this shape
(`HttpxAbiOpenPositionLookupAdapter` / `open_position_codec.py`); this
change adds only the missing implementation, following that philosophy and
Runtime's existing compact error model (an `Unavailable` family covering
timeout/network/internal failure, a `ProtocolError`, and one shared
`PublicError` carrying `status_code`/`code`/`message`/`details` — not a
class per ABI error code). No contradiction was found between the port,
the recipe models, and the authoritative ABI document.

## What Changes

- Add one synchronous HTTP adapter implementing
  `PositionManagementExecutionPort`: `apply_protection` →
  `PUT .../protection`, `close_position` → `DELETE .../open-position` (no
  body), each returning its confirmation only when the response fully
  matches the sent command.
- Add a strict codec against the authoritative ABI schemas, and a
  cross-repository OpenAPI conformance test.
- Classify failures using Runtime's existing shape: every documented
  public rejection (`malformed_json`, `unsupported_media_type`,
  `validation_failed`, `unknown_trade_cycle_binding`,
  `unsupported_exchange_scope`, and `position_not_open` — kept an ordinary
  rejection with no external-close handling) as one typed public-error
  result; timeout, network failure, and `internal_error` as one
  "unavailable" family; everything else as one protocol failure.
- One shared bounded timeout, one attempt per call, no retry, no
  redirects; opaque IDs encoded the same way as the existing ABI adapter.

## Non-Goals

- No production wiring, `StrategyRuntimeOrchestrator`/
  `PositionManagementOrchestrator` change, state/repository/mutex logic,
  external-close lifecycle, retry/recovery/pending-state/command-id
  mechanism, ABI/Bybit change, or general HTTP-infrastructure refactor.

## Capabilities

### New Capabilities

- `abi-position-management-client`: The synchronous HTTP implementation of
  `PositionManagementExecutionPort` against ABI's `protection` and
  `open-position` endpoints.

### Modified Capabilities

None. `position-management-orchestrator` is consumed exactly as already
ratified.

## Impact

New adapter, codec, and error modules under the existing `infrastructure/abi/`
area, plus matching contract tests. No production wiring, orchestrator,
state, or existing capability spec is changed.
