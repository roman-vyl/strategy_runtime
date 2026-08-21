## 1. Execution Model

- [x] 1.1 Add `exposure_fraction: str` to `ClosePositionCommand`, validated in
  `__post_init__` to equal the canonical Runtime V1 value `"1"` exactly (exact-decimal
  text, no float). No generic percentage/Decimal framework.

## 2. Command Builder

- [x] 2.1 `build_position_management_command`'s `ClosePosition` branch always sets
  `exposure_fraction="1"` on the built `ClosePositionCommand`. Trade decision semantics
  (close full exposure of the current trade cycle) unchanged.

## 3. HTTP Adapter

- [x] 3.1 `close_position` issues `POST .../close` with a closed JSON body
  `{"exposure_fraction": command.exposure_fraction}` and
  `content-type: application/json` / `accept: application/json` headers, replacing the
  bodyless `DELETE .../open-position` call.
- [x] 3.2 Preserve opaque path-segment percent-encoding, one bounded attempt, shared
  timeout, no retry, and disabled redirects.

## 4. Codec

- [x] 4.1 Update `_CLOSE_POSITION_PUBLIC_CODES` to ABI's current documented close error
  set: `422 validation_failed`, `422 unknown_trade_cycle_binding`, `422
  unsupported_exchange_scope`, `422 close_execution_incomplete`. `position_not_open`
  stays protection-only.
- [x] 4.2 Close success decoding, strict identifier verification, and fail-closed
  malformed/undocumented handling stay unchanged.

## 5. Tests

- [x] 5.1 `ClosePositionCommand` carries canonical `"1"`; rejects any other
  `exposure_fraction` value.
- [x] 5.2 `build_position_management_command` produces `exposure_fraction="1"` for
  `ClosePosition`.
- [x] 5.3 Contract test: `close_position` issues `POST` to exact `/close` path with exact
  JSON body `{"exposure_fraction": "1"}`; no `DELETE` request is made.
- [x] 5.4 Opaque identifier path encoding for the close path (mirroring existing
  protection/open-position parametrized cases).
- [x] 5.5 Success confirmation and mismatched-identifier fail-closed cases.
- [x] 5.6 Malformed/extra success-field fail-closed cases.
- [x] 5.7 Current documented close business errors including `close_execution_incomplete`;
  `position_not_open` at close is undocumented (protocol failure).
- [x] 5.8 Timeout / network-failure / internal-error unavailable classification; exactly
  one request per call, no retry.
- [x] 5.9 Update the authoritative ABI OpenAPI compatibility test to the `/close` `POST`
  operation, its `CloseRequest`/`TradeCycleClosedResponse`/`CloseBusinessError` schemas,
  and its documented examples; remove assertions on the retired `open-position` `DELETE`
  operation. Leave the pair-scoped GET open-position lookup contract test unchanged.

## 6. Validation

- [x] 6.1 Run targeted tests, full test suite, Ruff, mypy, `openspec validate --strict`.
