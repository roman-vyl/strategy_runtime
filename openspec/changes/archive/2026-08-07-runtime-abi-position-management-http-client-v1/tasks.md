## 1. Typed Errors and Codec

- [x] 1.1 Add the compact typed-error hierarchy mirroring
  `runtime/open_position/errors.py`: a base execution error; an
  `Unavailable` family used directly for `500 internal_error` and
  subclassed for timeout and network failure; a `ProtocolError`; and one
  `PublicError` (not a class per code) carrying `status_code`, `code`,
  `message`, and optional `details`, used for every documented public
  rejection including `position_not_open` (an ordinary rejection, no
  special case).
- [x] 1.2 Add a strict codec module decoding the `protection` `PUT` and
  `open-position` `DELETE` responses against
  `abi-position-management-api-v1.json`'s exact schemas: closed success
  objects, closed error envelopes per documented status/code, UTF-8 JSON
  content-type validation, no unknown/duplicate fields.
- [x] 1.3 Reject any response whose success body does not exactly match
  the sent command's identifiers and (for protection) `stop_price`/
  `take_price` as a protocol failure, not a confirmation.

## 2. HTTP Adapter

- [x] 2.1 Implement one adapter providing `PositionManagementExecutionPort`,
  mirroring `HttpxAbiOpenPositionLookupAdapter`'s construction shape: one
  shared finite positive `timeout_seconds`, redirects disabled, zero
  transport retries.
- [x] 2.2 `apply_protection`: `PUT .../protection` with a closed
  `{stop_price, take_price}` JSON body built from `desired_protection`.
- [x] 2.3 `close_position`: `DELETE .../open-position` with no body.
- [x] 2.4 Percent-encode `strategy_instance_id`/`trade_cycle_id` path
  segments using the same helper/approach as the existing ABI open-position
  adapter, including dot-only segments.
- [x] 2.5 Map `httpx` timeout/transport exceptions to the `Unavailable`
  timeout/network-failure subclasses; route all other responses through
  the codec.

## 3. Contract Tests

- [x] 3.1 Add a fake-ABI adapter test suite covering: successful matching
  responses for both operations; mismatched-identifier and
  mismatched-protection-value responses; every documented public error
  code per operation (including `position_not_open`); `500 internal_error`;
  malformed/undocumented responses (bad JSON, bad content-type, wrong
  fields, undocumented status, redirect) collapsed under the
  protocol-failure requirement; timeout; network failure.
- [x] 3.2 Assert exactly one HTTP attempt per call and no retry on any
  failure path.
- [x] 3.3 Add a cross-repository OpenAPI conformance test against
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

## 5. Verification (this apply pass)

- [x] 5.1 `ruff check` and `ruff format --check` over the new/modified
  source and test files — pass.
- [x] 5.2 `mypy` (strict, repository-wide) — passes, no issues.
- [x] 5.3 `python -m compileall` over `src` and `tests` — passes.
- [x] 5.4 Full `pytest` run (sibling `abi_executor_bot` checked out next
  to this repository) — 1011 passed, including 54 new tests in
  `tests/contract/abi/test_position_management_client.py` and
  `tests/contract/abi/test_position_management_openapi.py`.
- [x] 5.5 `git diff --check` — clean.
- [x] 5.6 Diff reviewed: limited to
  `runtime/position_management_execution/errors.py` (new error classes
  appended), two new `infrastructure/abi/` modules, and the two new
  contract test files — no production wiring, orchestrator, state, or
  existing capability spec touched.

## 6. Correction pass (review feedback)

- [x] 6.1 Fixed a contract blocker: the protection success codec compared
  `confirmed_protection` after both sides passed through
  `DesiredProtection`'s `normalize_decimal_text`, so a numeric-equivalent
  but differently formatted wire value (e.g. `"99000.0"` vs the sent
  `"99000"`) was silently accepted instead of failing closed. The codec
  now validates each raw wire string against the ABI
  positive-exact-decimal grammar, compares the raw strings/null directly
  against the sent command's values, and only constructs
  `DesiredProtection`/`ProtectionAppliedConfirmation` after that match
  succeeds.
- [x] 6.2 Loosened `error.details[].path`/`.message` decoding from
  non-empty to plain-string, matching the authoritative `ValidationDetail`
  schema (no `minLength`, unlike the envelope's own `error.message`,
  which does require `minLength: 1`).
- [x] 6.3 Strengthened the cross-repository OpenAPI conformance test to
  assert the exact `code` `const` for `malformed_json`,
  `unsupported_media_type`, and `internal_error` (previously only the
  schema `$ref` was checked), the full `stop_price`/`take_price`
  type+format schemas on both `ProtectionRequest` and
  `ProtectionAppliedResponse`, and the authoritative `ValidationDetail`
  schema shape.
- [x] 6.4 Added regression tests: numeric-equivalent-but-differently-
  formatted wire values are rejected; non-positive/malformed wire decimal
  text is rejected; empty `path`/`message` in validation details is
  accepted.
- [x] 6.5 Full verification re-run: `ruff check`/`ruff format --check`,
  `mypy` (strict, repository-wide), `python -m compileall`, and the full
  `pytest` suite (sibling `abi_executor_bot` checked out) — 1022 passed
  (11 new tests over the prior apply pass), `git diff --check` clean.
