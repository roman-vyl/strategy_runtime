## Why

`I4d` (`runtime-live-entry-production-composition-v1`, archived) wired
`HttpxAbiOpenPositionLookupAdapter` into production against
`GET /v1/strategy-instances/{strategy_instance_id}/open-position`, an
identity-only path returning `entry_bar_open_time_ms`/`executed_entry_price`.
The authoritative ABI implementation (`abi_executor_bot`, archived as
`abi-open-position-lookup-v1`, commit `ea5a18903f28d89f5f97a6b9a8c82ae395bf720a`)
shipped a different, incompatible contract:
`GET /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position`,
a pair-addressed lookup keyed by a composite `(strategy_instance_id,
trade_cycle_id)` that ABI's own `EntryPackageCorrelationRepository` only ever
learns via the entry-package PUT route, returning `first_fill_at_ms`/
`average_entry_price` and treating an unregistered pair as a fail-closed
`422 unknown_trade_cycle_binding`, never as `position_open: false`.

This is not a same-shape field rename. Runtime's current, ratified
`open-position-resolver` capability performs an unconditional identity-only
lookup — explicitly "without filtering by local lifecycle condition", even
when `current_trade_cycle` is absent — which the final ABI contract cannot
satisfy: a request with no known `trade_cycle_id` has no path parameter to
send, and ABI classifies an unregistered pair as an error, not a closed
position. An architectural pre-pass (see this change's design.md) resolved
this as a trade-cycle-conditional lookup: skip the ABI call when
`current_trade_cycle is None` (the only state in which no `trade_cycle_id`
can exist yet) and call ABI with the existing `trade_cycle_id` once one has
been created by a prior `Apply`. This is the accepted Live V1 in-memory
lifecycle model, not a restart-recovery mechanism; durable state remains a
separate, later change.

This change aligns Runtime's ABI open-position lookup client, its nearest
domain models, the resolver's call semantics, and every dependent test with
this final authoritative contract, and separately closes a handful of
small I4d documentation/config loose ends discovered while re-reading the
archived I4d change against the current repository state.

## What Changes

- **BREAKING** Change `AbiOpenPositionLookupPort`'s wire target from
  `GET /v1/strategy-instances/{strategy_instance_id}/open-position` to
  `GET /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/open-position`,
  percent-encoding both opaque path segments (mirroring the existing
  `HttpxAbiEntryPackageAdapter` two-segment pattern), with no Runtime-side
  regex/format validation on either identifier.
- **BREAKING** Rewrite `open_position_codec.py` against the authoritative
  ABI OpenAPI (`abi-open-position-lookup-api-v1.json`): closed `oneOf` success
  variants discriminated by `position_open` (`const true`/`const false`),
  `first_fill_at_ms` (strictly positive integer) and `average_entry_price`
  (positive exact-decimal string) replacing `entry_bar_open_time_ms`/
  `executed_entry_price`; a `422` envelope decoded per exact code
  (`validation_failed` requires a non-empty `details` array of
  `{path, message}`; `unknown_trade_cycle_binding` and
  `unsupported_exchange_scope` permit no `details` field at all — not a
  uniform optional-`details` envelope); a `500` envelope restricted to
  `internal_error` with no `details`. No transformation, computation, or
  rounding of `first_fill_at_ms`/`average_entry_price` is introduced; both
  are carried through unchanged in value and meaning.
- **BREAKING** Rename `OpenPositionLookupResponse.entry_bar_open_time_ms` /
  `.executed_entry_price` to `.first_fill_at_ms` / `.average_entry_price`,
  and add a required `trade_cycle_id` field to `OpenPositionLookupRequest`.
  Propagate the same rename into
  `PositionResolvedStrategyInstanceRuntimeState`. `first_fill_at_ms` and
  `average_entry_price` remain ABI/Runtime execution facts in this change;
  neither is mapped into, renamed into, or otherwise made to reach any
  Strategy Engine request field.
- **BREAKING** Change `StrategyUseCaseRouter`'s open-trade branch: for
  `position_open=true`, the router no longer constructs
  `OpenTradeProjectionRequest` or calls `StrategyEngineOpenTradePort` at
  all. It raises the existing `OpenTradeContextUnavailable` unconditionally,
  fail-closed, before any Engine call — a temporary boundary pending a
  separate future design of how, or whether, `first_fill_at_ms`/
  `average_entry_price` should ever reach Strategy Engine.
  `position_open=false` is unaffected and continues to call
  `StrategyEngineLiveEntryPort` exactly as before.
- Change `OpenPositionResolver.resolve(state)` from an unconditional
  identity-only lookup to a trade-cycle-conditional one: when
  `state.current_trade_cycle is None`, no ABI call is made and the resolver
  returns a local closed result (`position_open=False`) enabling live-entry
  routing; when a `CurrentTradeCycle` exists, the resolver calls ABI with
  `state.current_trade_cycle.trade_cycle_id`. This supersedes the archived
  `open-position-resolver` capability's "identity-only, unconditional"
  requirement for the reasons captured in design.md; restart recovery,
  identity-only lookup, and lost-trade-cycle search remain explicitly out of
  scope.
- Add a fail-closed classification for `unknown_trade_cycle_binding` returned
  against a `trade_cycle_id` Runtime believes is registered — a Runtime/ABI
  state divergence, decoded as the existing `OpenPositionLookupPublicError`
  (`code="unknown_trade_cycle_binding"`) and propagated unchanged, never
  coerced into `position_open=false`.
- Add the authoritative cross-repository contract test that reads
  `../abi_executor_bot/docs/openapi/abi-open-position-lookup-api-v1.json`
  directly and verifies path, method, required path parameters, the success
  `oneOf`, field consts/nullability/`additionalProperties`, every documented
  error status and its exact per-code schema (including the `details` rule
  difference above) — not a property-name-only check.
- Update production E2E fixtures (`_fake_http_server.py`,
  `test_production_e2e.py`) to the final success/error payload shapes; add a
  regression test proving the legacy success shape
  (`entry_bar_open_time_ms`/`executed_entry_price`) is now rejected as a
  protocol error, and a closed-response happy-path test proving Runtime still
  reaches the Strategy Engine live-entry route.
- Fix a small, unrelated set of I4d closure gaps discovered while
  cross-checking the archived change against the current repository:
  `config/runtime.env.example` never received the five `I4d` outbound
  variables; `runtime-master-plan.md` and `runtime-abi-entry-delivery-map.md`
  (and its generated HTML fragments) still describe `I4d` as pending/NEXT
  even though it is implemented and archived; and the archived `I4d`
  `tasks.md` §11 still shows unchecked "documentation sync and archive"
  items inside an already-archived change. This change corrects the
  discrepancy without silently rewriting `I4d`'s history (see design.md).
- Remove the empty, untracked, duplicate change scaffold
  `openspec/changes/runtime-production-composition-i4d-v1/` (contains no
  files; confirmed not tracked by Git) left over from an earlier, superseded
  attempt to re-propose already-archived `I4d` work.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `abi-open-position-lookup-client`: Replace the identity-only URI, response
  field names, and error-envelope decoding rules with the final pair-addressed
  ABI contract (path, success `oneOf`, per-code error schemas).
- `open-position-resolver`: Replace the unconditional identity-only lookup
  requirement with a trade-cycle-conditional one (skip ABI when no current
  trade cycle exists; call ABI with the existing `trade_cycle_id` otherwise),
  and document the accepted Live V1 in-memory lifecycle boundary this rests
  on.
- `use-case-router`: Replace the open-trade mapping requirement. For
  `position_open=true` the router SHALL NOT construct
  `OpenTradeProjectionRequest` or call `StrategyEngineOpenTradePort`; it
  SHALL raise the existing `OpenTradeContextUnavailable` unconditionally.
  `position_open=false` continues to call `StrategyEngineLiveEntryPort`
  unchanged. This is a temporary fail-closed boundary, not a permanent
  design decision about Engine's open-trade contract.

## Impact

- Affected production code (not modified in this proposal-only step; listed
  for the future implementation): `runtime/open_position/models.py`,
  `ports.py`, `errors.py`, `resolver.py`; `infrastructure/abi/
  http_open_position.py`, `open_position_codec.py`; `runtime/routing/
  router.py` (open-trade branch becomes unconditionally fail-closed before
  any Engine call — no field mapping, no request construction);
  `config/model.py` and
  `loader.py` are not changed by this alignment (the five I4d outbound
  variables already exist there; only `runtime.env.example` is out of sync).
- Affected tests: `tests/contract/abi/test_open_position_client.py`,
  `tests/unit/runtime/test_semantic_pipeline.py`,
  `tests/integration/committed_bar/test_production_e2e.py`,
  `tests/integration/committed_bar/_fake_http_server.py`, plus a new
  authoritative cross-repository OpenAPI contract test.
- Depends on a canonical sibling checkout,
  `BBB_project/{strategy_runtime,abi_executor_bot}`, with `abi_executor_bot`
  at `ea5a18903f28d89f5f97a6b9a8c82ae395bf720a`, for both design verification
  and the new contract test.
- No change to `EntryReconciliationOrchestrator`, `AbiEntryPackagePort`, the
  ABI entry-package client/bridge, `StrategyRuntimeOrchestrator`'s keyed
  critical section, the `runtime-production-composition` composition graph,
  or any Strategy Engine contract.
- Explicitly out of scope: restart recovery, identity-only ABI lookup, search
  for a lost trade cycle, durable repository, distributed locking, startup
  reconciliation against the exchange, timestamp normalization or candle-grid
  alignment, deciding how or whether `first_fill_at_ms`/
  `average_entry_price` should ever reach Strategy Engine, a new open-trade
  lifecycle, and any ABI/Engine-side change.
