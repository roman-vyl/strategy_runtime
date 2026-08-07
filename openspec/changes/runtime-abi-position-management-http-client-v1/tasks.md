## 1. Typed Errors and Codec

- [ ] 1.1 Add typed failures for: each documented public error code per
  operation (including `position_not_open` as an ordinary typed public
  error, not a special case), `internal_error`, protocol failure, timeout,
  and network failure — following the existing
  `runtime/open_position/errors.py` shape.
- [ ] 1.2 Add a strict codec module decoding the `protection` `PUT` and
  `open-position` `DELETE` responses against
  `abi-position-management-api-v1.json`'s exact schemas: closed success
  objects, closed error envelopes per documented status/code, UTF-8 JSON
  content-type validation, no unknown/duplicate fields.
- [ ] 1.3 Reject any response whose success body does not exactly match
  the sent command's identifiers and (for protection) `stop_price`/
  `take_price` as a protocol failure, not a confirmation.

## 2. HTTP Adapter

- [ ] 2.1 Implement one adapter providing `PositionManagementExecutionPort`,
  mirroring `HttpxAbiOpenPositionLookupAdapter`'s construction shape: one
  shared finite positive `timeout_seconds`, redirects disabled, zero
  transport retries.
- [ ] 2.2 `apply_protection`: `PUT .../protection` with a closed
  `{stop_price, take_price}` JSON body built from `desired_protection`.
- [ ] 2.3 `close_position`: `DELETE .../open-position` with no body.
- [ ] 2.4 Percent-encode `strategy_instance_id`/`trade_cycle_id` path
  segments using the same helper/approach as the existing ABI open-position
  adapter, including dot-only segments.
- [ ] 2.5 Map `httpx` timeout/transport exceptions to the typed timeout/
  network failures; route all other responses through the codec.

## 3. Contract Tests

- [ ] 3.1 Add a fake-ABI adapter test suite covering: successful matching
  responses for both operations; mismatched-identifier and
  mismatched-protection-value responses; every documented public error
  code per operation (including `position_not_open`); `500 internal_error`;
  malformed/undocumented responses (bad JSON, bad content-type, wrong
  fields, undocumented status, redirect) collapsed under the
  protocol-failure requirement; timeout; network failure.
- [ ] 3.2 Assert exactly one HTTP attempt per call and no retry on any
  failure path.
- [ ] 3.3 Add a cross-repository OpenAPI conformance test against
  `abi-position-management-api-v1.json`, mirroring the existing
  `test_open_position_openapi.py` pattern (sibling-checkout resolution,
  actionable error if the sibling is absent).

## 4. Verification (this proposal pass)

- [x] 4.1 `npm exec -- openspec validate
  runtime-abi-position-management-http-client-v1 --strict` passes.
- [x] 4.2 `npm exec -- openspec validate --all --strict` passes with no
  regression to any existing spec or change.
- [x] 4.3 Confirmed no production or test code was modified — only files
  under
  `openspec/changes/runtime-abi-position-management-http-client-v1/` were
  added.
