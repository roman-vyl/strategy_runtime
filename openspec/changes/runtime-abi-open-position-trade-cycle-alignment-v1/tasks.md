## 1. Runtime Domain Models and Ports

- [ ] 1.1 Add a required `trade_cycle_id: str` field to
  `OpenPositionLookupRequest` (`runtime/open_position/models.py`), validated
  non-empty like the existing `strategy_instance_id`.
- [ ] 1.2 Rename `OpenPositionLookupResponse.entry_bar_open_time_ms` /
  `.executed_entry_price` to `.first_fill_at_ms` / `.average_entry_price`;
  tighten the open-position invariant from non-negative to strictly
  positive for `first_fill_at_ms`, matching the authoritative
  `exclusiveMinimum: 0` schema.
- [ ] 1.3 Rename `PositionResolvedStrategyInstanceRuntimeState
  .entry_bar_open_time_ms` / `.executed_entry_price` to `.first_fill_at_ms` /
  `.average_entry_price`.
- [ ] 1.4 Confirm `AbiOpenPositionLookupPort` / `OpenPositionResolverPort`
  (`runtime/open_position/ports.py`) need no signature change beyond the
  request/response model changes above.

## 2. Resolver: Trade-Cycle-Conditional Lookup

- [ ] 2.1 Change `OpenPositionResolver.resolve(state)`
  (`runtime/open_position/resolver.py`) to branch on
  `state.current_trade_cycle`: when `None`, return
  `PositionResolvedStrategyInstanceRuntimeState(runtime_state=state,
  position_open=False, first_fill_at_ms=None, average_entry_price=None)`
  without calling `AbiOpenPositionLookupPort`; when present, build
  `OpenPositionLookupRequest(strategy_instance_id=state.strategy_instance_id,
  trade_cycle_id=state.current_trade_cycle.trade_cycle_id)` and call the
  port exactly once.
- [ ] 2.2 Confirm the resolver still lets every `AbiOpenPositionLookupPort`
  exception (including a documented `unknown_trade_cycle_binding`
  `OpenPositionLookupPublicError`) propagate uncaught — no new
  try/except is introduced.

## 3. ABI Open-Position HTTP Adapter and Codec

- [ ] 3.1 Change the adapter's path builder
  (`infrastructure/abi/http_open_position.py`) to
  `/v1/strategy-instances/{strategy_segment}/trade-cycles/{cycle_segment}/open-position`,
  percent-encoding both `strategy_instance_id` and `trade_cycle_id`
  independently via the existing opaque-path-segment helper (mirror the
  existing two-segment pattern in `runtime/abi/entry_package_http.py`'s
  `_entry_package_path`).
- [ ] 3.2 Rewrite `decode_open_position_response`
  (`infrastructure/abi/open_position_codec.py`) success decoding: closed
  fields exactly `position_open`/`first_fill_at_ms`/`average_entry_price`;
  `position_open` literal `true`/`false`; open variant requires a strictly
  positive integer `first_fill_at_ms` and a JSON-string
  `average_entry_price` (parsed without `float` conversion, then
  domain-normalized by the response model); closed variant requires both
  other fields to be `null`.
- [ ] 3.3 Rewrite error decoding: `422` only (not `400`), discriminated by
  `error.code` into exactly `validation_failed` (requires non-empty
  `details` array of closed `{path, message}` objects),
  `unknown_trade_cycle_binding` (forbids a `details` field),
  `unsupported_exchange_scope` (forbids a `details` field); any other code
  or shape becomes `OpenPositionLookupProtocolError`.
- [ ] 3.4 Rewrite `5xx` decoding: only `500` with the closed
  `{error: {code: "internal_error", message}}` envelope (no `details`)
  becomes `OpenPositionLookupUnavailable`; any other `5xx` shape, code, or a
  `details` field present becomes `OpenPositionLookupProtocolError`.
- [ ] 3.5 Confirm timeout/network-failure/redirect/malformed-JSON/
  unexpected-status handling in the adapter needs no change beyond the
  fields above (these branches are status/transport-driven, not
  field-shape-driven).

## 4. Router Field Propagation

- [ ] 4.1 Update `StrategyUseCaseRouter`'s open-trade branch
  (`runtime/routing/router.py`) to read `resolved.first_fill_at_ms` /
  `resolved.average_entry_price` in place of the renamed fields, passing
  `first_fill_at_ms` through unchanged as
  `OpenTradeProjectionRequest.entry_bar_open_time_ms` (Engine's own,
  unrelated field name — not renamed, not recomputed).
- [ ] 4.2 Confirm no other production module references
  `entry_bar_open_time_ms`/`executed_entry_price` as ABI-origin field names
  (grep for both identifiers across `src/` after 1–4 land; any remaining
  hit outside `runtime/engine/`, `infrastructure/strategy_engine/`, and
  Engine-contract test files is a missed rename).

## 5. Contract Tests

- [ ] 5.1 Update `tests/contract/abi/test_open_position_client.py`: both
  path segments and their independent percent-encoding/dot-only cases; both
  success variants under the new field names and tightened
  `first_fill_at_ms` positivity; each of the three `422` codes with its
  exact per-code envelope (including the two `details`-forbidden cases and
  the `details`-required case); the `500 internal_error` envelope; rejection
  of a `400` as undocumented; rejection of a `details` field present on
  `unknown_trade_cycle_binding`/`unsupported_exchange_scope`/`500`; timeout,
  network failure, redirect rejection, and single-attempt cardinality
  (mostly unchanged, re-verify against the new path).
- [ ] 5.2 Add a regression test asserting the pre-alignment success shape
  (`entry_bar_open_time_ms`/`executed_entry_price`) is rejected as
  `OpenPositionLookupProtocolError`.
- [ ] 5.3 Add the authoritative cross-repository contract test that loads
  `../abi_executor_bot/docs/openapi/abi-open-position-lookup-api-v1.json`
  and asserts: exact path template and method; both required path
  parameters; the success `oneOf`'s two variants with their `position_open`
  `const`, required/nullable fields, and `additionalProperties: false`;
  every documented error status and its exact per-code schema, including
  which codes require vs. forbid `details`. Fail with a clear message
  explaining the required `BBB_project/{strategy_runtime,abi_executor_bot}`
  sibling checkout layout if `../abi_executor_bot` is absent.

## 6. Resolver and Semantic-Pipeline Tests

- [ ] 6.1 Add/extend resolver unit tests: no ABI call and a local closed
  result when `current_trade_cycle is None`; exactly one ABI call using
  `current_trade_cycle.trade_cycle_id` when present; an
  `unknown_trade_cycle_binding` `OpenPositionLookupPublicError` propagates
  uncaught and unconverted.
- [ ] 6.2 Update `tests/unit/runtime/test_semantic_pipeline.py` fixtures and
  assertions for the renamed fields and the new request shape (`Abi` fake's
  `lookup` call site and any `PositionResolvedStrategyInstanceRuntimeState`/
  `OpenPositionLookupResponse` construction).
- [ ] 6.3 Update
  `tests/unit/runtime/entry_reconciliation_orchestrator/test_entry_reconciliation_orchestrator.py`
  and any other test file matched by
  `grep -rl entry_bar_open_time_ms\|executed_entry_price tests/unit` for the
  renamed fields.

## 7. Production E2E Fixtures

- [ ] 7.1 Update `tests/integration/committed_bar/_fake_http_server.py` and
  `tests/integration/committed_bar/test_production_e2e.py` fake ABI
  open-position responses to the final path and success/error payload
  shapes.
- [ ] 7.2 Add/confirm a happy-path test: closed-bar webhook → ABI returns
  the final closed response (no trade cycle yet, so no ABI call is actually
  made — assert zero ABI open-position requests) → Strategy Engine
  live-entry route is called → pipeline does not fail with a protocol
  error.
- [ ] 7.3 Add a second happy-path test covering the case where a current
  trade cycle already exists: ABI open-position lookup is called with the
  existing `trade_cycle_id`, using the final closed response shape, and the
  live-entry route is still reached.
- [ ] 7.4 Add a negative test proving the pre-alignment success shape
  (`entry_bar_open_time_ms`/`executed_entry_price`) is no longer accepted —
  the cycle fails closed (no repository save, failed dispatch outcome
  journaled) rather than being silently coerced.
- [ ] 7.5 Add a test proving the open-position-open path performs no
  implicit legacy-field synthesis and exercises the existing fail-closed
  open-trade behavior (`OpenTradeProjectionUnsupportedError`) unchanged.

## 8. I4d Closure Corrections (Unrelated, Small)

- [ ] 8.1 Add the five `I4d` outbound variables
  (`RUNTIME_STRATEGY_ENGINE_BASE_URL`,
  `RUNTIME_STRATEGY_ENGINE_TIMEOUT_SECONDS`, `RUNTIME_ABI_BASE_URL`,
  `RUNTIME_ABI_OPEN_POSITION_TIMEOUT_SECONDS`,
  `RUNTIME_ABI_ENTRY_PACKAGE_TIMEOUT_SECONDS`) to
  `config/runtime.env.example`, matching the values already required by
  `config/loader.py`.
- [ ] 8.2 Update `docs/system-plans/runtime-master-plan.md` and
  `docs/system-plans/runtime-abi-entry-delivery-map.md` to mark `I4d` as
  implemented/archived rather than pending/`NEXT`, matching the composition
  graph actually delivered by
  `openspec/changes/archive/2026-07-30-runtime-live-entry-production
  -composition-v1/`. Update the generated
  `runtime-abi-entry-delivery-map.html` /
  `.fragment.html` artifacts to match, following the diff pattern
  established when a prior change last updated them together with the
  `.md` source.
- [ ] 8.3 Do not edit any file under
  `openspec/changes/archive/2026-07-30-runtime-live-entry-production
  -composition-v1/`. Its `tasks.md` §11 checkboxes remain unchecked as an
  accurate historical record; this task list performs the deferred
  documentation work instead (see design.md, "Documentation sync without
  rewriting I4d's history").
- [ ] 8.4 Re-confirm `openspec/changes/runtime-production-composition-i4d-v1/`
  is still empty (`ls -la`) and untracked (`git status --porcelain`), then
  remove the directory. Skip this task without failing the change if either
  check no longer holds, and note why.

## 9. Full Verification

- [ ] 9.1 Run `pytest` from `strategy_runtime/` with `abi_executor_bot`
  checked out as a sibling directory
  (`BBB_project/{strategy_runtime,abi_executor_bot}`) at
  `ea5a18903f28d89f5f97a6b9a8c82ae395bf720a`, so both the existing ABI
  entry-package OpenAPI conformance test and the new open-position
  cross-repository contract test can resolve their sibling-repo paths.
- [ ] 9.2 Run `ruff check` and `ruff format --check`.
- [ ] 9.3 Run `mypy`.
- [ ] 9.4 Run `python -m compileall` over the changed source tree.
- [ ] 9.5 Run
  `openspec validate runtime-abi-open-position-trade-cycle-alignment-v1
  --strict`.
- [ ] 9.6 Run `openspec validate --all --strict`.
- [ ] 9.7 Run `git diff --check`.
- [ ] 9.8 Audit the final diff to confirm it is limited to the open-position
  client/resolver/router propagation, its tests, and the unrelated small
  I4d closure items in section 8 — no change to
  `EntryReconciliationOrchestrator`, the ABI entry-package client/bridge,
  `StrategyRuntimeOrchestrator`'s critical section, the
  `runtime-production-composition` graph, or any Strategy Engine contract.
