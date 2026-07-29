## 1. Shared Failure Taxonomies and Codec Helpers

- [x] 1.1 Add the Strategy Engine projection failure taxonomy under
  `runtime/engine/errors.py`: `StrategyEngineProjectionError` (base) and
  `StrategyEngineProjectionUnavailable`, which is the superclass of
  `StrategyEngineProjectionPublicError`, `StrategyEngineProjectionTimeout`,
  `StrategyEngineProjectionNetworkFailure`, and
  `StrategyEngineProjectionProtocolError` — matching the canonical
  `use-case-router` contract that treats every Engine HTTP failure branch as
  `StrategyEngineProjectionUnavailable`. `StrategyEngineProjectionPublicError`
  preserves `status_code`, `code`, `message`, `details`, and `request_id`;
  `StrategyEngineMarketStreamNotFound` is its subtype for HTTP `404` + code
  `market_stream_not_found`.
- [x] 1.2 Extend the existing `runtime/open_position/errors.py` hierarchy with
  `OpenPositionLookupTimeout` and `OpenPositionLookupNetworkFailure` as subclasses
  of the existing `OpenPositionLookupUnavailable`, and add
  `OpenPositionLookupPublicError` as a new subclass of
  `OpenPositionResolutionError`; keep the existing
  `OpenPositionLookupProtocolError` for malformed/undocumented responses.
- [x] 1.3 Add `EntryReconciliationExecutionError` as the typed bridge failure;
  place it under the entry-reconciliation-orchestrator boundary without
  coupling it to HTTP types. A returned `EntryPackagePublicError` result
  becomes `error.public_error`, with no `__cause__` (nothing was caught or
  re-raised); a raised ABI exception (`AbiEntryPackageTimeout`,
  `AbiEntryPackageNetworkFailure`, `AbiEntryPackageProtocolError`) is
  preserved as `__cause__`.
- [x] 1.4 Decide whether to introduce one shared codec helper across all three
  new HTTP adapters. Decision: do not introduce it. The two Strategy Engine
  adapters share their Engine-local wire codec; ABI open-position retains its
  separate codec; the existing ABI entry-package client remains untouched.

## 2. Strategy Engine Live-Entry Client

- [x] 2.1 Add closed wire request DTO mirroring the accepted Engine
  `POST /v1/strategy-evaluations/live-entry` body:
  `strategy_id`, `raw_spec`, `ticker`, `base_timeframe`,
  `target_bar_open_time_ms` (JSON integer, not boolean).
- [x] 2.2 Add closed wire response DTOs for the singular `desired_entry: … | null`
  shape and the closed `DesiredEntry` wire object (six fields), rejecting missing,
  unknown, or mistyped fields and JSON-numeric price fields.
- [x] 2.3 Implement `HttpxStrategyEngineLiveEntryAdapter` implementing
  `StrategyEngineLiveEntryPort.project_live_entry` with a finite positive
  timeout, `httpx.HTTPTransport(retries=0)`, `follow_redirects=False`, and exactly
  one `POST` per call.
- [x] 2.4 Strictly decode only HTTP `200` with the closed success body; map the
  wire `DesiredEntry` into the existing `runtime.recipes.entry.DesiredEntry`
  (invariants applied) and preserve `desired_entry = null` without fabricating a
  side.
- [x] 2.5 Decode documented non-`2xx` responses (closed
  `{error, message, details, request_id}` envelope) into
  `StrategyEngineProjectionPublicError` preserving status, code, message,
  details, and `request_id`; decode HTTP `404` + code `market_stream_not_found`
  into `StrategyEngineMarketStreamNotFound`.
- [x] 2.6 Map timeout to `StrategyEngineProjectionTimeout`, non-timeout network
  transport failure to `StrategyEngineProjectionNetworkFailure`, and
  undocumented status, incompatible content type, malformed JSON, invalid UTF-8,
  or body-outside-DTO to `StrategyEngineProjectionProtocolError`.
- [x] 2.7 Keep the adapter unconnected to `StrategyUseCaseRouter`,
  `StrategyRuntimeOrchestrator`, `build_application`, repository, mutex, and
  production configuration.

## 3. Strategy Engine Open-Trade Client

- [x] 3.1 Add closed wire request DTO mirroring the accepted Engine
  `POST /v1/strategy-evaluations/open-trade` body, regrouping the existing
  `OpenTradeProjectionRequest` flat fields into the `executed_trade_receipt`
  envelope (seven fields) without adding `executed_entry_price`,
  `strategy_instance_id`, or `trade_cycle_id`.
- [x] 3.2 Add closed wire response DTOs for `desired_protection` (closed,
  `stop_price`, `take_price: str | None`) and `close_signal` (closed, `active`,
  `reason`, `component_id`, `layer`), rejecting missing, unknown, or mistyped
  fields.
- [x] 3.3 Decode `diagnostics` as an arbitrary JSON object (must be a JSON
  object, not array/scalar) and freeze it recursively into the existing
  `Mapping[str, FrozenJsonValue]`; do not validate any fixed internal
  diagnostics field set.
- [x] 3.4 Implement `HttpxStrategyEngineOpenTradeAdapter` implementing
  `StrategyEngineOpenTradePort.project_open_trade` with the same bounded,
  non-retried, no-redirect transport discipline as the live-entry adapter.
- [x] 3.5 Strictly decode only HTTP `200` with the closed success body; map wire
  `desired_protection` and `close_signal` into the existing
  `runtime.recipes.position_management.DesiredProtection` and `CloseSignal`
  domain models (invariants applied).
- [x] 3.6 Apply the same Engine failure taxonomy as the live-entry adapter
  (tasks 2.5–2.6) to documented non-`2xx`, timeout, network, and protocol
  outcomes.
- [x] 3.7 Keep the adapter unconnected to `StrategyUseCaseRouter`,
  `StrategyRuntimeOrchestrator`, `build_application`, repository, mutex, and
  production configuration.

## 4. ABI Open-Position Lookup Client

- [x] 4.1 Add the closed wire success DTO for
  `GET /v1/strategy-instances/{strategy_instance_id}/open-position` matching the
  focused plan: `position_open: bool`, `entry_bar_open_time_ms: int | null`,
  `executed_entry_price: str | null`, with the validity rules that an open
  position requires both entry facts and a closed position carries neither.
- [x] 4.2 Implement `HttpxAbiOpenPositionLookupAdapter` implementing
  `AbiOpenPositionLookupPort.lookup` with a finite positive timeout,
  `httpx.HTTPTransport(retries=0)`, `follow_redirects=False`, and exactly one
  `GET` per call.
- [x] 4.3 Percent-encode `strategy_instance_id` as one opaque UTF-8 path segment,
  preserving slash, percent, Unicode, whitespace, and dot-only values; do not
  impose Runtime-side regex/format validation on the identifier.
- [x] 4.4 Treat only HTTP `200` with `position_open=false` as "no open position";
  never coerce an unexpected `404` or any other non-`2xx` into
  `position_open=false`.
- [x] 4.5 Map a documented ABI `400`/`422` public error (valid parse of the
  nested `{error: {code, message}}` envelope, with a required non-empty
  `code`/`message` and an optional `details` — a missing `details` is not a
  protocol error) to `OpenPositionLookupPublicError`; map a documented `5xx`
  status with a valid parse of that envelope to `OpenPositionLookupUnavailable`;
  map timeout to `OpenPositionLookupTimeout`, non-timeout network failure to
  `OpenPositionLookupNetworkFailure`, and undocumented status, unexpected `404`,
  incompatible content type, malformed JSON, an unknown envelope field, a
  missing/invalid `code` or `message`, or body-outside-DTO (including an
  unparseable envelope) to `OpenPositionLookupProtocolError`.
- [x] 4.6 Map the decoded success body into the existing
  `OpenPositionLookupResponse` domain model (invariants applied, including
  decimal normalization of `executed_entry_price` without binary-float
  conversion).
- [x] 4.7 Keep the adapter unconnected to `OpenPositionResolver`,
  `StrategyRuntimeOrchestrator`, `build_application`, repository, mutex, and
  production configuration.

## 5. Entry Reconciliation Execution Bridge

- [x] 5.1 Implement `AbiEntryPackageExecutionBridge` implementing
  `EntryReconciliationExecutionPort.execute(command, source_state)` as a pure
  translator with no HTTP transport, URL encoding, timeout configuration, mutex,
  repository, retry, or state mutation.
- [x] 5.2 Read `risk_multiplier` from `source_state.risk_multiplier` and map
  `command.desired_entry` (`DesiredEntry | None`) into
  `EntryPackageWireDesiredEntry | None`; construct one `EntryPackageRequest` from
  `command.strategy_instance_id`, `command.trade_cycle_id`, `command.ticker`,
  the mapped desired entry, and the sourced `risk_multiplier`.
- [x] 5.3 Call the existing `AbiEntryPackagePort.send` exactly once per
  `execute(...)` invocation.
- [x] 5.4 Map `EntryPackageApplied` to `EntryAppliedConfirmation` (mapping
  `applied_desired_entry` wire DTO back into the domain `DesiredEntry`) and
  `EntryPackageAbsent` to `EntryAbsentConfirmation`.
- [x] 5.5 Map `EntryPackagePublicError` (a returned result value, not a raised
  exception) to `EntryReconciliationExecutionError(public_error=result)` with
  no `__cause__` (nothing was caught or re-raised). Map each raised exception
  (`AbiEntryPackageTimeout`, `AbiEntryPackageNetworkFailure`,
  `AbiEntryPackageProtocolError`) to `EntryReconciliationExecutionError(...)
  raised from <original exception>`, preserving it as `__cause__`.
- [x] 5.6 Keep the bridge unconnected to `EntryReconciliationOrchestrator`,
  `StrategyRuntimeOrchestrator`, `build_application`, repository, mutex, and
  production configuration.

## 6. ABI Entry-Package Client DTO Cleanup

- [x] 6.1 Remove `accepted_risk_multiplier` from `EntryPackageApplied` in
  `runtime/abi/entry_package_models.py` and drop its positive-exact-decimal
  validation.
- [x] 6.2 Remove `accepted_risk_multiplier` from `_APPLIED_FIELDS` and the
  applied-success decode path in `runtime/abi/entry_package_codec.py`; ensure the
  strict decoder rejects an ABI response that still carries the field as unknown.
- [x] 6.3 Update every fake-ABI fixture and contract test in
  `tests/contract/abi/test_entry_package_client.py` to no longer emit or assert
  `accepted_risk_multiplier`.
- [x] 6.3a Gate (external prerequisite, unchecked until confirmed): confirm
  the sibling ABI OpenAPI document has removed `accepted_risk_multiplier`
  before running or updating the Runtime conformance assertion in task 6.4 and
  before final `I4c` verification/sign-off. `I4c` does not modify or own the
  ABI repository; this task only confirms the external cleanup has landed.
- [x] 6.4 Update the ABI OpenAPI conformance test in
  `tests/contract/abi/test_entry_package_openapi.py` to assert the applied
  success DTO no longer contains `accepted_risk_multiplier`.
- [x] 6.5 Do not change the request DTO (`risk_multiplier` remains mandatory
  one-way), the absent success DTO, the public-error mappings, the HTTP
  transport, or the timeout/redirect behavior of the existing client.

## 7. Fake-HTTP Contract Tests

- [x] 7.1 Add a controllable fake Strategy Engine HTTP server that records the
  raw request and emits every live-entry success, public-error, timeout,
  network-failure, malformed-response, redirect, and undocumented-status case.
- [x] 7.2 Test live-entry request shape (exact method, route, content type,
  closed body, JSON-integer timestamp, no Runtime identity fields), success
  decoding including `desired_entry = null`, every public-error branch with
  preserved `code`/`message`/`details`/`request_id`, `market_stream_not_found`
  subtype, timeout, network failure, protocol error, redirect rejection, and
  single-attempt cardinality.
- [x] 7.3 Add a controllable fake Strategy Engine HTTP server for the open-trade
  endpoint and test request shape (closed body, `executed_trade_receipt`
  regrouping, no `executed_entry_price`/`strategy_instance_id`/`trade_cycle_id`),
  success decoding (closed `desired_protection`/`close_signal`, opaque
  `diagnostics`), every public-error branch, timeout, network failure, protocol
  error, redirect rejection, and single-attempt cardinality.
- [x] 7.4 Add a controllable fake ABI HTTP server for the open-position endpoint
  and test path-segment encoding (slash, percent, Unicode, whitespace,
  dot-only), `position_open=false` success, `position_open=true` success with
  string-JSON decimal decoding (no float conversion) and correct
  domain-normalized `executed_entry_price` (not byte-identical round-trip),
  unexpected `404` rejection, documented public error, a documented `5xx` with
  a valid envelope mapping to `OpenPositionLookupUnavailable`, timeout,
  network failure, protocol error, malformed body, redirect rejection, and
  single-attempt cardinality.
- [x] 7.5 Assert that no unconfirmed outcome (timeout, network failure, public
  error, protocol error, redirect) can produce a success result for any of the
  three adapters.

## 8. Bridge Unit and Translation Tests

- [x] 8.1 Test `command + source_state` → `EntryPackageRequest` mapping,
  including `risk_multiplier` sourced from `source_state` and `DesiredEntry` →
  `EntryPackageWireDesiredEntry` mapping for both present and absent packages.
- [x] 8.2 Test `EntryPackageApplied` → `EntryAppliedConfirmation` mapping
  (including wire `DesiredEntry` → domain `DesiredEntry`) and
  `EntryPackageAbsent` → `EntryAbsentConfirmation` mapping.
- [x] 8.3 Test that the `EntryPackagePublicError` result value produces
  `EntryReconciliationExecutionError` with no `__cause__` asserted (it is a
  returned value, not a caught/re-raised exception), and that each raised
  exception (`AbiEntryPackageTimeout`, `AbiEntryPackageNetworkFailure`,
  `AbiEntryPackageProtocolError`) produces `EntryReconciliationExecutionError`
  with the original exception preserved as `__cause__`.
- [x] 8.4 Test that the bridge calls `AbiEntryPackagePort.send` exactly once per
  `execute(...)` and performs no retry, mutex acquisition, repository access, or
  state mutation.
- [x] 8.5 Test that the bridge does not own HTTP, URL encoding, or timeout
  configuration by asserting it has no `httpx` dependency and accepts any
  `AbiEntryPackagePort` fake.

## 9. Architecture and Scope Guardrails

- [x] 9.1 Add or extend architecture tests proving the three HTTP adapters and
  the bridge are not constructed by `build_application`, not referenced by
  `StrategyRuntimeOrchestrator`, `OpenPositionResolver`, `StrategyUseCaseRouter`,
  or `EntryReconciliationOrchestrator`, and not wired into production
  configuration.
- [x] 9.2 Prove the bridge has no HTTP transport ownership (no `httpx` import, no
  URL/timeout configuration) and depends only on `AbiEntryPackagePort`,
  `EntryReconciliationCommand`, `StrategyInstanceRuntimeState`, and the
  confirmation/error types.
- [x] 9.3 Prove the existing ABI entry-package HTTP client changes are limited to
  the `accepted_risk_multiplier` removal (DTO field, codec field-set, decode
  path, fixtures, conformance test) with no transport, timeout, redirect, or
  public-error mapping change.
- [x] 9.4 Confirm no `RuntimeConfig`, `config/loader.py`, `build_application`,
  `bootstrap/application.py`, MDS webhook, vertical E2E, fill webhook, or
  open-trade application code is changed.
- [x] 9.5 Confirm no canonical OpenSpec or system-plan file is changed during
  implementation.

## 10. Verification

- [x] 10.1 Run the focused fake-HTTP contract tests for the three new adapters
  and the bridge unit/translation tests.
- [x] 10.2 Run the updated ABI entry-package client contract and OpenAPI
  conformance tests.
- [x] 10.3 Run the complete Runtime pytest suite, Ruff lint and format checks,
  mypy, and Python compilation checks using the repository's established
  verification commands.
- [x] 10.4 Run strict OpenSpec validation for
  `runtime-production-outbound-adapters-v1`.
- [x] 10.5 Run repository-wide strict OpenSpec validation.
- [x] 10.6 Run `git diff --check`.
- [x] 10.7 Audit the final implementation diff to confirm the change is limited
  to the three new HTTP adapters, the bridge, the shared failure taxonomies, the
  `accepted_risk_multiplier` removal, and their tests, with every deferred
  integration seam and planning/canonical file unchanged.
