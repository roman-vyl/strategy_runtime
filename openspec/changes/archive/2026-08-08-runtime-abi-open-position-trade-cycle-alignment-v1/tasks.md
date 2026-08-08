## 1. Runtime Domain Models and Ports

- [x] 1.1 Add a required `trade_cycle_id: str` field to
  `OpenPositionLookupRequest` (`runtime/open_position/models.py`), validated
  non-empty like the existing `strategy_instance_id`.
- [x] 1.2 Rename `OpenPositionLookupResponse.entry_bar_open_time_ms` /
  `.executed_entry_price` to `.first_fill_at_ms` / `.average_entry_price`;
  tighten the open-position invariant from non-negative to strictly
  positive for `first_fill_at_ms`, matching the authoritative
  `exclusiveMinimum: 0` schema.
- [x] 1.3 Rename `PositionResolvedStrategyInstanceRuntimeState
  .entry_bar_open_time_ms` / `.executed_entry_price` to `.first_fill_at_ms` /
  `.average_entry_price`.
- [x] 1.4 Confirm `AbiOpenPositionLookupPort` / `OpenPositionResolverPort`
  (`runtime/open_position/ports.py`) need no signature change beyond the
  request/response model changes above.

## 2. Resolver: Trade-Cycle-Conditional Lookup

- [x] 2.1 Change `OpenPositionResolver.resolve(state)`
  (`runtime/open_position/resolver.py`) to branch on
  `state.current_trade_cycle`: when `None`, return
  `PositionResolvedStrategyInstanceRuntimeState(runtime_state=state,
  position_open=False, first_fill_at_ms=None, average_entry_price=None)`
  without calling `AbiOpenPositionLookupPort`; when present, build
  `OpenPositionLookupRequest(strategy_instance_id=state.strategy_instance_id,
  trade_cycle_id=state.current_trade_cycle.trade_cycle_id)` and call the
  port exactly once.
- [x] 2.2 Confirm the resolver still lets every `AbiOpenPositionLookupPort`
  exception (including a documented `unknown_trade_cycle_binding`
  `OpenPositionLookupPublicError`) propagate uncaught — no new
  try/except is introduced.

## 3. ABI Open-Position HTTP Adapter and Codec

- [x] 3.1 Change the adapter's path builder
  (`infrastructure/abi/http_open_position.py`) to
  `/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/open-position`,
  percent-encoding both `strategy_instance_id` and `trade_cycle_id`
  independently via the existing opaque-path-segment helper (mirror the
  existing two-segment pattern in `runtime/abi/entry_package_http.py`'s
  `_entry_package_path`).
- [x] 3.2 Rewrite `decode_open_position_response`
  (`infrastructure/abi/open_position_codec.py`) success decoding: closed
  fields exactly `position_open`/`first_fill_at_ms`/`average_entry_price`;
  `position_open` literal `true`/`false`; open variant requires a strictly
  positive integer `first_fill_at_ms` and a JSON-string
  `average_entry_price` (parsed without `float` conversion, then
  domain-normalized by the response model); closed variant requires both
  other fields to be `null`.
- [x] 3.3 Rewrite error decoding: `422` only (not `400`), discriminated by
  `error.code` into exactly `validation_failed` (requires non-empty
  `details` array of closed `{path, message}` objects),
  `unknown_trade_cycle_binding` (forbids a `details` field),
  `unsupported_exchange_scope` (forbids a `details` field); any other code
  or shape becomes `OpenPositionLookupProtocolError`.
- [x] 3.4 Rewrite `5xx` decoding: only `500` with the closed
  `{error: {code: "internal_error", message}}` envelope (no `details`)
  becomes `OpenPositionLookupUnavailable`; any other `5xx` shape, code, or a
  `details` field present becomes `OpenPositionLookupProtocolError`.
- [x] 3.5 Confirm timeout/network-failure/redirect/malformed-JSON/
  unexpected-status handling in the adapter needs no change beyond the
  fields above (these branches are status/transport-driven, not
  field-shape-driven).

## 4. Router: Fail-Closed Open-Trade Boundary

- [x] 4.1 Change `StrategyUseCaseRouter`'s open-trade branch
  (`runtime/routing/router.py`) to raise `OpenTradeContextUnavailable(unit
  .strategy_instance_id)` unconditionally when `resolved.position_open` is
  `true`, before evaluating the current trade cycle, its frozen desired
  entry, or either fill fact. Remove the `OpenTradeProjectionRequest`
  construction and the `StrategyEngineOpenTradePort.project_open_trade`
  call from this branch entirely — do not read, copy, or rename
  `resolved.first_fill_at_ms` / `resolved.average_entry_price` anywhere in
  the router, and do not synthesize `entry_bar_open_time_ms` or
  `executed_entry_price`.
- [x] 4.2 Add a router unit test: given a fully-formed resolved state
  (`position_open=true`, an existing frozen current trade cycle, and real
  `first_fill_at_ms`/`average_entry_price` values), the router still raises
  `OpenTradeContextUnavailable` and makes zero calls to
  `StrategyEngineOpenTradePort` — proving the fail-closed boundary applies
  even when the "old" completeness check would have passed, not only when
  context looks incomplete.
- [x] 4.3 Confirm no other production module references
  `entry_bar_open_time_ms`/`executed_entry_price` as ABI-origin field names
  (grep for both identifiers across `src/` after 1–4 land; any remaining
  hit outside `runtime/engine/`, `infrastructure/strategy_engine/`, and
  Engine-contract test files is a missed rename). Confirm
  `OpenTradeProjectionRequest`/`StrategyEngineOpenTradePort` are not
  referenced anywhere in `runtime/routing/router.py` after this task group.

## 5. Contract Tests

- [x] 5.1 Update `tests/contract/abi/test_open_position_client.py`: both
  path segments and their independent percent-encoding/dot-only cases; both
  success variants under the new field names and tightened
  `first_fill_at_ms` positivity; each of the three `422` codes with its
  exact per-code envelope (including the two `details`-forbidden cases and
  the `details`-required case); the `500 internal_error` envelope; rejection
  of a `400` as undocumented; rejection of a `details` field present on
  `unknown_trade_cycle_binding`/`unsupported_exchange_scope`/`500`; timeout,
  network failure, redirect rejection, and single-attempt cardinality
  (mostly unchanged, re-verify against the new path).
- [x] 5.2 Add a regression test asserting the pre-alignment success shape
  (`entry_bar_open_time_ms`/`executed_entry_price`) is rejected as
  `OpenPositionLookupProtocolError`.
- [x] 5.3 Add the authoritative cross-repository contract test that loads
  `../abi_executor_bot/docs/openapi/abi-open-position-lookup-api-v1.json`
  and asserts: exact path template and method; both required path
  parameters; the success `oneOf`'s two variants with their `position_open`
  `const`, required/nullable fields, and `additionalProperties: false`;
  every documented error status and its exact per-code schema, including
  which codes require vs. forbid `details`. Fail with a clear message
  explaining the required `BBB_project/{strategy_runtime,abi_executor_bot}`
  sibling checkout layout if `../abi_executor_bot` is absent.

## 6. Resolver and Semantic-Pipeline Tests

- [x] 6.1 Add/extend resolver unit tests: no ABI call and a local closed
  result when `current_trade_cycle is None`; exactly one ABI call using
  `current_trade_cycle.trade_cycle_id` when present; an
  `unknown_trade_cycle_binding` `OpenPositionLookupPublicError` propagates
  uncaught and unconverted.
- [x] 6.2 Update `tests/unit/runtime/test_semantic_pipeline.py` fixtures and
  assertions for the renamed fields and the new request shape (`Abi` fake's
  `lookup` call site and any `PositionResolvedStrategyInstanceRuntimeState`/
  `OpenPositionLookupResponse` construction). Remove or rewrite any existing
  test in this file that asserts a *successful* open-trade Engine call for
  complete context — that outcome no longer exists after task group 4;
  replace it with (or fold it into) an assertion matching task 4.2's
  unconditional-fail-closed behavior.
- [x] 6.3 Update
  `tests/unit/runtime/entry_reconciliation_orchestrator/test_entry_reconciliation_orchestrator.py`
  and any other test file matched by
  `grep -rl entry_bar_open_time_ms\|executed_entry_price tests/unit` for the
  renamed fields.

## 7. Production E2E Fixtures

- [x] 7.1 Update `tests/integration/committed_bar/_fake_http_server.py` and
  `tests/integration/committed_bar/test_production_e2e.py` fake ABI
  open-position responses to the final path and success/error payload
  shapes.
- [x] 7.2 Add/confirm a happy-path test for a brand-new strategy instance:
  closed-bar webhook → `current_trade_cycle is None` so the resolver never
  calls ABI at all (assert the fake ABI open-position server records zero
  requests for this cycle) → Strategy Engine live-entry route is called →
  pipeline does not fail with a protocol error. Do not configure a fake ABI
  open-position response for this scenario — there is nothing to answer.
- [x] 7.3 Add a separate happy-path test covering the case where a current
  trade cycle already exists: the fake ABI server actually receives one
  open-position request for `(strategy_instance_id, trade_cycle_id)` and
  returns the final closed response shape
  (`position_open: false, first_fill_at_ms: null, average_entry_price:
  null`); the live-entry route is still reached.
- [x] 7.4 Add a negative test proving the pre-alignment success shape
  (`entry_bar_open_time_ms`/`executed_entry_price`) is no longer accepted —
  the cycle fails closed (no repository save, failed dispatch outcome
  journaled) rather than being silently coerced.
- [x] 7.5 Add an E2E test for the case where a current trade cycle already
  exists and the fake ABI server returns the final **open** response
  (`position_open: true, first_fill_at_ms: <positive int>,
  average_entry_price: "<positive decimal>"`): assert the response is
  decoded successfully (no protocol error), assert the Strategy Engine
  open-trade endpoint receives zero requests, assert no repository save
  occurs, and assert the cycle is recorded as a failed dispatch outcome via
  the existing `OpenTradeContextUnavailable` → `CommittedBarOrchestrator`
  path. Assert no legacy field name
  (`entry_bar_open_time_ms`/`executed_entry_price`) appears anywhere in the
  request Strategy Engine would have received, had it been called.

## 8. I4d Closure Corrections (Unrelated, Small)

- [x] 8.1 Add the five `I4d` outbound variables
  (`RUNTIME_STRATEGY_ENGINE_BASE_URL`,
  `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
  `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`) to
  `config/runtime.env.example`, matching the values already required by
  `config/loader.py`.
- [x] 8.2 Update `docs/system-plans/runtime-master-plan.md` and
  `docs/system-plans/runtime-abi-entry-delivery-map.md` to mark `I4d` as
  implemented/archived rather than pending/`NEXT`, matching the composition
  graph actually delivered by
  `openspec/changes/archive/2026-07-30-runtime-live-entry-production
  -composition-v1/`. Update the generated
  `runtime-abi-entry-delivery-map.html` /
  `.fragment.html` artifacts to match, following the diff pattern
  established when a prior change last updated them together with the
  `.md` source.
- [x] 8.3 Do not edit any file under
  `openspec/changes/archive/2026-07-30-runtime-live-entry-production
  -composition-v1/`. Its `tasks.md` §11 checkboxes remain unchecked as an
  accurate historical record; this task list performs the deferred
  documentation work instead (see design.md, "Documentation sync without
  rewriting I4d's history").
- [x] 8.4 Re-confirm `openspec/changes/runtime-production-composition-i4d-v1/`
  is still empty (`ls -la`) and untracked (`git status --porcelain`), then
  remove the directory. Skip this task without failing the change if either
  check no longer holds, and note why.

## 9. Full Verification

- [x] 9.1 Run `pytest` from `strategy_runtime/` with `abi_executor_bot`
  checked out as a sibling directory
  (`BBB_project/{strategy_runtime,abi_executor_bot}`) at
  `ea5a18903f28d89f5f97a6b9a8c82ae395bf720a`, so both the existing ABI
  entry-package OpenAPI conformance test and the new open-position
  cross-repository contract test can resolve their sibling-repo paths.
- [x] 9.2 Run `ruff check` and `ruff format --check`.
- [x] 9.3 Run `mypy`.
- [x] 9.4 Run `python -m compileall` over the changed source tree.
- [x] 9.5 Run
  `openspec validate runtime-abi-open-position-trade-cycle-alignment-v1
  --strict`.
- [x] 9.6 Run `openspec validate --all --strict`.
- [x] 9.7 Run `git diff --check`.
- [x] 9.8 Audit the final diff to confirm it is limited to the open-position
  client/resolver/router propagation, its tests, and the unrelated small
  I4d closure items in section 8 — no change to
  `EntryReconciliationOrchestrator`, the ABI entry-package client/bridge,
  `StrategyRuntimeOrchestrator`'s critical section, the
  `runtime-production-composition` graph, or any Strategy Engine contract.
