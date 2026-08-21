## Why

ABI's pair-scoped close endpoint has moved to `POST .../close` with a canonical
`exposure_fraction` body (`abi-position-management-api` spec, sibling repo
`abi_executor_bot`, branch `integration/change7-current-design`), replacing the retired
`DELETE .../open-position` empty-body form. Runtime's outbound close client still issues
the old bodyless `DELETE`, which no longer resolves to ABI's close capability — every
Runtime close request would now hit ABI's generic not-found response instead of closing
anything.

## What Changes

- `close_position` issues `POST .../close` with a closed JSON body
  `{"exposure_fraction": "1"}` instead of a bodyless `DELETE .../open-position`.
- `ClosePositionCommand` carries an explicit `exposure_fraction` field, fixed to the
  canonical Runtime V1 value `"1"` (exact-decimal text, not float). No other value is
  accepted; V1 supports only canonical full close, not arbitrary partial close.
- `build_position_management_command` always sets `exposure_fraction="1"` for
  `ClosePosition` decisions; trade decision semantics are unchanged — it still means
  "close the entire exposure of the current trade cycle."
- The close codec's documented public-error set is updated to match current ABI:
  `validation_failed`, `unknown_trade_cycle_binding`, `unsupported_exchange_scope`, and
  the new close-only `close_execution_incomplete`. `position_not_open` remains
  protection-only, unchanged.
- Close success confirmation, strict identifier verification, fail-closed decoding,
  single bounded non-retried HTTP attempt, and opaque path-segment encoding are all
  preserved unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `abi-position-management-client`: outbound close request moves from bodyless `DELETE
  .../open-position` to `POST .../close` with `{"exposure_fraction": "1"}`; documented
  close business errors are updated to ABI's current set.

## Impact

- Affects `ClosePositionCommand`, `build_position_management_command`,
  `HttpxAbiPositionManagementAdapter.close_position`, and
  `decode_close_position_response`.
- Does not affect `apply_protection`, the pair-scoped GET open-position lookup, Engine
  contracts/DTOs, strategy decision logic, or any ABI-side implementation.
- Does not introduce quantity calculation, arbitrary partial close, a generic
  Decimal/percentage subsystem, or retry/idempotency behavior.
