## Why

The closed-bar Runtime orchestration (`I4a`/`I4b`) is implemented and archived,
but none of its outbound dependencies is reachable from production. Of the five
application ports the semantic core depends on, four are exercised only through
fakes (`StrategyEngineLiveEntryPort`, `StrategyEngineOpenTradePort`,
`AbiOpenPositionLookupPort`, `EntryReconciliationExecutionPort`) and the fifth
(`AbiEntryPackagePort`) already has a real, contract-tested HTTP client that is
simply not composed into the application yet.

`I4c` closes that gap in isolation: it implements and contract-tests the three
missing production HTTP adapters and one application-level execution bridge, and
removes the single known DTO mismatch from the already-shipped ABI entry-package
client. It stops before any production composition, configuration, lifecycle, or
vertical E2E wiring — that is `I4d`.

## What Changes

- Implement a production HTTP adapter for `StrategyEngineLiveEntryPort` against
  `POST /v1/strategy-evaluations/live-entry` using closed wire request/response
  DTOs that strictly decode the accepted Strategy Engine contract and map into
  the existing Runtime `DesiredEntry | null` projection model.
- Implement a production HTTP adapter for `StrategyEngineOpenTradePort` against
  `POST /v1/strategy-evaluations/open-trade` using closed wire DTOs that regroup
  the existing Runtime `OpenTradeProjectionRequest` fields into the Engine
  `executed_trade_receipt` envelope without introducing any new execution fact,
  and that strictly decode the closed `desired_protection` and `close_signal`
  objects while preserving `diagnostics` as an opaque recursively immutable JSON
  mapping.
- Implement a production HTTP adapter for `AbiOpenPositionLookupPort` against
  `GET /v1/strategy-instances/{strategy_instance_id}/open-position`, fixing the
  Runtime-side wire contract for that endpoint: HTTP `200` with
  `position_open=false` means no open position, every other non-`2xx`, malformed,
  timeout, or transport outcome is a typed failure, and an unexpected `404` is
  never coerced into `position_open=false`.
- Implement the `EntryReconciliationExecutionPort` → `AbiEntryPackagePort`
  application bridge: translate one `EntryReconciliationCommand` plus its
  `source_state` into one `EntryPackageRequest`, call the existing ABI
  entry-package client exactly once, map a successful acknowledgement to the
  matching `SuccessfulEntryConfirmation` variant, and construct a typed
  `EntryReconciliationExecutionError` for any unconfirmed outcome.
  `EntryPackagePublicError` is a returned result value, not a raised
  exception, so the bridge builds
  `EntryReconciliationExecutionError(public_error=result)` directly with no
  `__cause__`; the raised `AbiEntryPackageTimeout`,
  `AbiEntryPackageNetworkFailure`, and `AbiEntryPackageProtocolError`
  exceptions are instead re-raised as `EntryReconciliationExecutionError(...)
  from <original exception>`, preserving `__cause__`. The bridge owns no HTTP
  transport, URL encoding, timeout configuration, mutex, repository access,
  retry, or state mutation.
- Introduce a granular typed failure taxonomy for the three HTTP adapters.
  Documented Strategy Engine non-`2xx` responses become
  `StrategyEngineProjectionPublicError` (or its `StrategyEngineMarketStreamNotFound`
  subtype), preserving status, code, message, details, and `request_id` — all
  as subtypes of `StrategyEngineProjectionUnavailable`, matching the canonical
  `use-case-router` contract. Documented ABI open-position `400`/`422`
  responses become `OpenPositionLookupPublicError` preserving status, code,
  message, and details, with no `request_id` (ABI's nested error envelope
  carries none); a documented ABI `5xx` becomes `OpenPositionLookupUnavailable`,
  not a public error. Timeout, network transport, and protocol/decoding
  failures become distinct typed exceptions for every adapter; no unconfirmed
  outcome is ever collapsed into a success result.
- Remove the obsolete `EntryPackageApplied.accepted_risk_multiplier` echo from
  the already-implemented ABI entry-package client DTO, codec, fake-ABI
  fixtures, and OpenAPI-conformance test. `risk_multiplier` travels to ABI
  one-way and is never returned or reconfirmed.
- Add fake-HTTP contract tests for each of the three new HTTP adapters
  (request shape, success decoding, every typed error branch, timeout,
  malformed response, redirect rejection, single-attempt cardinality) and
  ordinary typed unit/translation tests for the bridge against a fake
  `AbiEntryPackagePort`.
- Keep Runtime configuration, `build_application`, production composition, HTTP
  client lifecycle, MDS webhook wiring, vertical E2E, the ABI fill webhook, and
  the open-trade application operation outside this change.

## Capabilities

### New Capabilities

- `strategy-engine-live-entry-client`: Defines the Runtime-side outbound HTTP
  consumer contract, closed wire DTOs, strict decoding, granular typed failure
  taxonomy, bounded non-retried transport behavior, and fake-HTTP contract
  verification for `POST /v1/strategy-evaluations/live-entry`.
- `strategy-engine-open-trade-client`: Defines the Runtime-side outbound HTTP
  consumer contract, closed wire DTOs with the `executed_trade_receipt`
  regrouping, opaque diagnostics preservation, the same granular typed failure
  taxonomy, bounded non-retried transport behavior, and fake-HTTP contract
  verification for `POST /v1/strategy-evaluations/open-trade`.
- `abi-open-position-lookup-client`: Defines the Runtime-side outbound HTTP
  consumer contract for the open-position lookup endpoint fixed by the focused
  integration plan, including the `position_open=false` success semantics,
  path-segment encoding, typed public/timeout/network/protocol failure
  taxonomy, and fake-HTTP contract verification.
- `entry-reconciliation-execution-bridge`: Defines the application-level
  translator from `EntryReconciliationExecutionPort` to the existing
  `AbiEntryPackagePort`, including exact command-to-request mapping,
  `risk_multiplier` sourcing from `source_state`, success-to-confirmation
  mapping, and typed execution-failure propagation without HTTP, mutex,
  repository, retry, or state-mutation ownership.

### Modified Capabilities

- `abi-entry-package-client`: Remove the `accepted_risk_multiplier` echo from
  `EntryPackageApplied` and every dependent codec, fixture, and conformance
  assertion. `risk_multiplier` remains a mandatory one-way request field; ABI no
  longer returns or reconfirms it.

## Impact

- Future implementation will add new Runtime Engine HTTP adapter modules under
  the Runtime application/infrastructure boundary, a new ABI open-position HTTP
  adapter module, a new entry-execution bridge component, and a new shared
  Engine failure taxonomy, without rewriting the existing ABI entry-package HTTP
  client beyond the single DTO-field removal.
- The three HTTP adapters are constructed and tested in isolation; none is
  connected to `build_application`, `StrategyRuntimeOrchestrator`,
  `OpenPositionResolver`, `StrategyUseCaseRouter`, or
  `EntryReconciliationOrchestrator` by this change.
- The bridge calls the existing `AbiEntryPackagePort` and introduces no second
  HTTP transport for the entry-package endpoint.
- The `accepted_risk_multiplier` removal is a breaking change to the ABI
  entry-package client DTO. The ABI-side contract/OpenAPI cleanup removing the
  field — including the sibling ABI OpenAPI document the Runtime conformance
  test reads — is an external baseline prerequisite before task 6.4 and final
  `I4c` verification/sign-off; `I4c` does not modify or own the ABI
  repository. ABI's runtime deployment alignment (no longer actually
  returning the field) is a separate external prerequisite before `I4d`
  composes the client into production.
- No canonical spec or system-plan file is edited by this change.
