## Why

Strategy Runtime needs a production-ready outbound client contract for the
already approved ABI desired-entry-package endpoint. Without a strict consumer
boundary, Runtime cannot safely preserve exact-decimal values, distinguish
public ABI rejections from transport or protocol failures, or treat an
acknowledgement as bound to the intended Runtime-owned trade cycle.

## What Changes

- Add Runtime request and response DTOs that exactly mirror the approved ABI
  entry-package HTTP contract.
- Add a scalar outbound port for sending one desired entry package or its
  explicit absence.
- Require a positive exact-decimal `risk_multiplier` for every request,
  including a request with `desired_entry: null`; no null multiplier variant
  exists.
- Add an HTTP adapter boundary for the exact `PUT` route, JSON media type,
  percent-encoded ownership identifiers, and one bounded request.
- Preserve all exact-decimal values as strings without binary floating-point
  conversion.
- Strictly decode the two closed success DTOs and bind each acknowledgement to
  the originating `strategy_instance_id` and `trade_cycle_id`.
- Map the four public ABI error responses into typed Runtime client results
  without suppression, preserving validation details where required.
- Distinguish timeout, network, and invalid-response failures and fail closed
  whenever ABI has not returned a valid bound acknowledgement.
- Add fake-ABI contract tests and automated conformance checks against the
  approved ABI OpenAPI document.
- Keep reconciliation, `CurrentTradeCycle`, Runtime state mutation, persistence,
  and orchestrator wiring outside this change.

## Capabilities

### New Capabilities

- `abi-entry-package-client`: Defines the Runtime-side outbound port, HTTP
  consumer contract, strict decoding, error propagation, timeout behavior, and
  contract verification for the ABI V1 desired-entry-package endpoint.

### Modified Capabilities

None.

## Impact

- Future Runtime ABI client models, port, and HTTP adapter under the Runtime
  application/infrastructure boundary.
- Future client-level tests using a fake ABI server and the sibling ABI OpenAPI
  artifact as the wire-contract authority.
- One new outbound dependency direction from Runtime to the existing ABI HTTP
  endpoint; no ABI endpoint changes are introduced.
- No production or test implementation code, Runtime state, reconciliation,
  orchestrator flow, or persistence behavior is changed by this OpenSpec
  package.
