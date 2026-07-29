## Context

`EntryReconciliationOrchestrator` (`I4a`) and the closed-bar
`StrategyRuntimeOrchestrator` critical section (`I4b`) are implemented and
archived. `StrategyRuntimeOrchestrator.process(unit)` owns the complete keyed
critical section and returns the final `StrategyInstanceRuntimeState`. None of
this is reachable from production: `build_application` composes only the utility
contour and stops at an optional `StrategyCycleHandoffSink`.

Of the five application ports the semantic core depends on, four are exercised
only through fakes in tests:

```text
StrategyEngineLiveEntryPort
StrategyEngineOpenTradePort
AbiOpenPositionLookupPort
EntryReconciliationExecutionPort
```

The fifth, `AbiEntryPackagePort`, already has a real, contract-tested HTTP
implementation (`abi-entry-package-client-v1`) that is simply not composed into
the application yet. `I4c` implements the four missing pieces in isolation and
removes the single known DTO mismatch from the already-shipped client.

The accepted Strategy Engine and ABI wire contracts are treated as settled by
[`runtime-live-entry-production-integration-plan.md`](../../docs/system-plans/runtime-live-entry-production-integration-plan.md).
This change writes the adapters directly against those contracts and the
existing Runtime port definitions; no new Engine-side or ABI-side design work is
in scope.

## Goals / Non-Goals

**Goals:**

- Implement three production HTTP adapters (Strategy Engine live-entry, Strategy
  Engine open-trade, ABI open-position lookup) behind their existing application
  ports, each with closed wire DTOs, strict decoding, bounded non-retried
  transport, and a granular typed failure taxonomy.
- Implement one application-level execution bridge from
  `EntryReconciliationExecutionPort` to the existing `AbiEntryPackagePort`,
  without introducing a second HTTP transport.
- Map wire DTOs into the existing Runtime domain models without bypassing their
  invariants and without inventing additional domain rules at the wire seam.
- Make documented non-`2xx` responses typed public exceptions that preserve
  status, code, message, details, and `request_id`; make timeout, network, and
  protocol/decoding failures distinct typed exceptions; never collapse an
  unconfirmed outcome into a success.
- Remove the obsolete `accepted_risk_multiplier` echo from the ABI entry-package
  client DTO, codec, fixtures, and conformance test.
- Cover each HTTP adapter with fake-HTTP contract tests and the bridge with
  typed unit/translation tests against a fake `AbiEntryPackagePort`.
- Keep every adapter and the bridge unconnected to `build_application`,
  `StrategyRuntimeOrchestrator`, the repository, the keyed mutex, and production
  configuration.

**Non-Goals:**

- No Runtime configuration, `build_application` change, production composition,
  HTTP client lifecycle, startup readiness, or shutdown behavior.
- No MDS webhook wiring, vertical E2E, or cross-service integration test.
- No ABI fill webhook, `AbiExecutionEventOrchestrator`, or fill state machine.
- No open-trade application operation or position-management reconciliation.
- No general refactor of the existing ABI entry-package HTTP client; only the
  single `accepted_risk_multiplier` field is removed from its DTO, codec, and
  tests.
- No ABI-side or Strategy-Engine-side implementation change; `I4c` does not
  modify or own the ABI repository. The ABI-side contract-only cleanup
  removing `accepted_risk_multiplier` from the entry-package "applied"
  response — including the sibling ABI OpenAPI document the Runtime
  conformance test reads — is an external baseline prerequisite before task
  6.4 and final `I4c` verification. ABI's own production deployment alignment
  for the open-position endpoint remains an external prerequisite before
  `I4d`.
- No operational journaling or metrics for adapter outcomes.
- No repository CAS, command idempotency, restart recovery, or multi-worker
  deployment.
- No canonical spec or system-plan edits while this change is under review.

## Decisions

### Capability split: four new capabilities plus one modified capability

The four new components are architecturally distinct and get one capability
each, matching the per-capability discipline used by
`abi-entry-package-client-v1` and `closed-bar-runtime-orchestration-v1`:

```text
strategy-engine-live-entry-client        (new)
strategy-engine-open-trade-client        (new)
abi-open-position-lookup-client          (new)
entry-reconciliation-execution-bridge    (new)
abi-entry-package-client                 (modified — remove accepted_risk_multiplier)
```

Each capability owns its own spec, scenarios, and failure taxonomy. The two
Strategy Engine clients share the same Engine failure model but are peer
capabilities because they bind to distinct Engine endpoints, distinct Runtime
ports, and distinct request/response shapes.

**Rationale:** A single mega-capability would obscure which adapter a given
requirement constrains and would couple the open-trade wire contract to the
live-entry wire contract in one spec file. Peer capabilities keep each wire
contract independently evolvable.

**Alternative considered:** One `runtime-outbound-adapters` capability. Rejected
because the three HTTP adapters and the bridge have different transport
ownership, different test surfaces, and different failure semantics.

### Wire DTOs strictly check the external contract, then map to existing domain models

Each HTTP adapter introduces closed wire request and response DTOs that mirror
the accepted external contract exactly. The wire decoder enforces closed-object
semantics (reject missing, unknown, mistyped fields), exact-decimal text for
prices, JSON-integer (not boolean) timestamps, and the approved success shape.
After strict decoding, the wire object is mapped into the existing Runtime
domain model (`DesiredEntry`, `DesiredProtection`, `CloseSignal`,
`OpenPositionLookupResponse`).

The mapping does not bypass domain invariants: `DesiredEntry` construction
still applies `normalize_decimal_text` and positive-`initial_take_price`
enforcement. The wire codec also does not invent additional domain rules: no
timestamp range, price ordering, decimal-text-length, or profile-content
constraint is added beyond what the external contract and the existing domain
model already require.

```text
Engine wire DesiredEntry (6 fields, closed)
  → strict decode → EntryPackageWireDesiredEntry-equivalent wire DTO
  → map → runtime.recipes.entry.DesiredEntry (invariants applied)
```

**Rationale:** Reusing a richer domain model directly at the JSON boundary could
silently narrow or widen the wire contract. A separate wire DTO that strictly
mirrors the external contract, followed by an explicit mapping into the domain
model, keeps the two concerns decoupled and makes contract drift detectable.

**Alternative considered:** Serialize/deserialize `DesiredEntry` directly. Its
internal normalization and positivity rules are not the normative external
schema, and a future Engine field addition would either break Runtime silently or
be accepted without a deliberate contract decision.

### Decimal fields decode as JSON strings without float conversion; byte-for-value preservation is scoped to wire-only DTO fields

All prices, `risk_multiplier`, `calculated_quantity`, and ABI open-position
`executed_entry_price` arrive and are validated as JSON strings, never through
a binary floating-point (`float`) conversion. That guarantee is universal
across the three new HTTP clients and the existing ABI entry-package client.

Byte-for-value / exact-lexeme preservation is a narrower, separate guarantee
that applies only where a decimal value stays a wire DTO field that is never
converted into a domain type for computation — this is the case for the
existing ABI entry-package client's `EntryPackageApplied`/`EntryPackageRequest`
fields (`applied_desired_entry`, `calculated_quantity`, `risk_multiplier`),
which remain untouched wire DTOs.

For the three new HTTP clients (Strategy Engine live-entry, Strategy Engine
open-trade, ABI open-position lookup), decimal fields that map into an
existing Runtime domain model (`DesiredEntry`, `DesiredProtection`,
`OpenPositionLookupResponse`) go through that domain model's existing
`normalize_decimal_text` and invariant rules. The decoded value is therefore
domain-normalized, not guaranteed byte-identical to the original wire lexeme.
Tests for these three clients assert string-JSON parsing without float
conversion and the correct domain-normalized value, not byte-identical
round-trip.

**Rationale:** Engine and ABI own numeric interpretation at the wire boundary;
Runtime must not introduce a `float` conversion. But once a decimal value
crosses into an existing domain model that already normalizes decimal text
(as `DesiredEntry` does), preserving the exact original lexeme would require
bypassing that domain model's own normalization — which is out of scope here.

### Engine failure model: granular typed exceptions, not a single Unavailable bucket

The Strategy Engine returns a closed error envelope for every non-`2xx`:

```json
{
  "error": "...",
  "message": "...",
  "details": {},
  "request_id": "..."
}
```

The adapter introduces a granular typed failure taxonomy:

```text
StrategyEngineProjectionError                       (base)
└── StrategyEngineProjectionUnavailable             (superclass of every HTTP-failure branch)
    ├── StrategyEngineProjectionPublicError         (documented non-2xx business rejection)
    │   └── StrategyEngineMarketStreamNotFound      (HTTP 404 + code market_stream_not_found)
    ├── StrategyEngineProjectionTimeout
    ├── StrategyEngineProjectionNetworkFailure
    └── StrategyEngineProjectionProtocolError
```

- Documented non-`2xx` responses (the closed `{error, message, details,
  request_id}` envelope for `404`, `409`, `422`, `500`, `501`, `502`, `503`)
  become `StrategyEngineProjectionPublicError` (or its
  `StrategyEngineMarketStreamNotFound` subtype for the distinguishable
  `market_stream_not_found` condition required by the focused plan). The
  exception preserves `status_code`, `code`, `message`, `details`, and
  `request_id`.
- A request timeout becomes `StrategyEngineProjectionTimeout`.
- A non-timeout network transport failure becomes
  `StrategyEngineProjectionNetworkFailure`.
- An undocumented status, incompatible content type, malformed JSON, invalid
  UTF-8, or a body outside the exact DTO for its status becomes
  `StrategyEngineProjectionProtocolError`.

`StrategyEngineProjectionUnavailable` is the single superclass of every
HTTP-failure branch — `StrategyEngineProjectionPublicError` (and its
`StrategyEngineMarketStreamNotFound` subtype), `StrategyEngineProjectionTimeout`,
`StrategyEngineProjectionNetworkFailure`, and `StrategyEngineProjectionProtocolError`
are all `StrategyEngineProjectionUnavailable` subclasses. This matches the
canonical `use-case-router` capability spec, which already establishes that
Strategy Engine HTTP failures — including documented non-`2xx` business
rejections, not only transport/timeout/protocol failures — are represented as
`StrategyEngineProjectionUnavailable`. `I4c` preserves that existing contract
rather than modifying it: the router continues to see every branch as an
`Unavailable` instance and propagates it unchanged, while the granular
subtypes give Runtime and future callers the finer-grained diagnostics
(`status_code`, `code`, `message`, `details`, `request_id` for public errors;
a distinct type for timeout vs. network vs. protocol failures).

`StrategyEngineMarketStreamNotFound` is the only business-specific subtype in
`I4c`, because the focused plan explicitly requires it to be distinguishable.
Other documented codes (`unknown_resource`, `market_stream_not_ready`,
`target_bar_not_committed`, `trade_history_unavailable`, `invalid_request`,
`unsupported_capability`, `upstream_contract_error`, `market_data_unavailable`,
`evaluation_invariant_broken`, `internal_error`) remain generic
`StrategyEngineProjectionPublicError` instances with their `code` preserved as
an attribute. Adding more specific subtypes is a future decision, not an `I4c`
goal.

**Rationale:** Collapsing documented business rejections into an
undifferentiated "unavailable" would discard actionable Engine diagnostics and
make a `404 market_stream_not_found` indistinguishable from a transport
failure. Collapsing timeout/network/protocol into one type would prevent
callers from distinguishing ambiguous outcomes from hard transport failures.
Nesting all four branches under `StrategyEngineProjectionUnavailable` keeps
every branch satisfying the existing `use-case-router` contract while adding
the granularity the focused plan requires.

**Alternative considered:** A single undifferentiated
`StrategyEngineProjectionUnavailable` for all non-`2xx` and transport failures
(the stub behavior referenced by the existing `use-case-router` spec).
Rejected because it loses the Engine error taxonomy and the `request_id`
needed for later operational journaling.

### ABI open-position failure model: symmetric granular taxonomy

The ABI open-position adapter introduces a parallel taxonomy, reusing the
existing `OpenPositionResolutionError` hierarchy so the existing
`open-position-resolver` specification ("distinguish lookup availability
failures from protocol-invalid responses") remains satisfied:

```text
OpenPositionResolutionError                          (existing base)
├── OpenPositionLookupUnavailable                   (existing — availability)
│   ├── OpenPositionLookupTimeout                   (new)
│   └── OpenPositionLookupNetworkFailure            (new)
├── OpenPositionLookupProtocolError                 (existing — malformed/undocumented)
└── OpenPositionLookupPublicError                   (new — documented non-2xx)
```

ABI errors use the ABI-style nested envelope, not the Engine-style flat
envelope: a closed top-level object containing only an `error` key, whose
value carries `code`, `message`, and `details`. ABI entry-package responses do
not carry `request_id`, and this envelope model does not assert one either:

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "details": {}
  }
}
```

`details` remains opaque/untyped JSON until the ABI-side OpenAPI is published;
this design does not over-specify its shape.

- `GET /v1/strategy-instances/{strategy_instance_id}/open-position` returning
  HTTP `200` with `position_open=false` is the only success outcome meaning "no
  open position".
- An unexpected `404`, any undocumented status, or a malformed/unparseable
  envelope is **not** a closed position; it is decoded as
  `OpenPositionLookupProtocolError`, never coerced into `position_open=false`.
- HTTP `400`/`422` with a valid parse of the nested `{error: {code, message,
  details}}` envelope (ABI's future path/encoding validation contract) becomes
  `OpenPositionLookupPublicError`.
- A documented `5xx` status with a valid parse of the envelope becomes
  `OpenPositionLookupUnavailable` (its `ServiceUnavailable`-style transport
  cluster, consistent with the timeout/network-failure subtypes below), not a
  public error.
- Timeout, network, and protocol/decoding failures map to their distinct
  subtypes of `OpenPositionLookupUnavailable` / `OpenPositionLookupProtocolError`.

`strategy_instance_id` is treated as an opaque external identifier: Runtime does
not impose its own regex/format validation before sending it to ABI. A malformed
request or path-encoding problem is ABI's own public error, decoded as a typed
public failure; Runtime does not invent the validation rule itself.

**Rationale:** The focused plan fixes the rule that only `200` with
`position_open=false` means "no open position"; every other outcome must be a
typed failure. Reusing the existing resolver-side hierarchy keeps the
`open-position-resolver` spec scenarios valid (subclasses are-a
`OpenPositionLookupUnavailable` / `OpenPositionLookupProtocolError`) while
adding the granularity the plan requires.

### No ABI open-position OpenAPI conformance test in I4c

Unlike the ABI entry-package client, no authoritative ABI open-position OpenAPI
document exists yet. `I4c` therefore covers the open-position adapter with
fake-HTTP contract tests only. A conformance check against a future sibling ABI
OpenAPI document is deferred until ABI publishes that contract; it is not
required for the `I4c` exit condition (adapters constructed and tested in
isolation).

**Rationale:** A conformance test against a missing or hand-written local
fixture would be internally consistent but would not detect real contract drift.
Deferring avoids inventing an ABI contract from the Runtime side.

### Open-trade request is a pure rename/regroup; no new execution facts

The Runtime port model `OpenTradeProjectionRequest` carries flat fields:

```text
strategy_id, raw_spec, ticker, base_timeframe, target_bar_open_time_ms,
desired_entry: DesiredEntry, entry_bar_open_time_ms: int
```

The Engine wire request groups the frozen entry plan and its execution bar into
one `executed_trade_receipt` envelope:

```text
strategy_id, raw_spec, ticker, base_timeframe, target_bar_open_time_ms,
executed_trade_receipt:
    side, source_plan_bar_open_time_ms, entry_bar_open_time_ms,
    planned_entry_price, initial_stop_price, initial_take_price,
    locked_exit_profile
```

The adapter is a pure rename/regroup of the same fields the port model already
carries. It does **not** add `executed_entry_price`, `strategy_instance_id`, or
`trade_cycle_id` — consistent with the established rule that
`executed_entry_price` stays a Runtime/ABI execution fact never sent to Engine,
and that Runtime business identities do not cross the Engine boundary.

### Open-trade diagnostics remain opaque at the Runtime domain layer

The Engine `OpenTradeProjectionResponseModel.diagnostics` is a closed Pydantic
object (`extra="forbid"`) with six fixed fields. The Runtime wire adapter
enforces the closed top-level response shape (exactly `desired_protection`,
`close_signal`, `diagnostics`) and the closed `desired_protection` and
`close_signal` nested objects, but decodes `diagnostics` as an arbitrary JSON
object (must be a JSON object, not array/scalar) and freezes it recursively into
the existing `Mapping[str, FrozenJsonValue]`.

This preserves the existing `use-case-router` contract: the router and
downstream Runtime treat diagnostics as opaque and require no fixed diagnostic
field list. The wire adapter enforces only that `diagnostics` is a JSON object;
it does not validate the Engine's six internal fields, so an Engine diagnostics
schema change does not break Runtime as long as the value remains a JSON object.

**Rationale:** `desired_protection` and `close_signal` map 1:1 to Runtime domain
models with invariants, so they are strictly decoded. `diagnostics` is
explicitly opaque by the existing router contract; strict-checking its internal
fields would couple Runtime to an Engine-internal schema that the router is
explicitly forbidden from interpreting.

### Entry execution bridge: pure translator, no HTTP

`EntryReconciliationExecutionPort.execute(command, source_state)` is the
application-side execution boundary already called by
`EntryReconciliationOrchestrator`. `I4c` implements the concrete bridge:

```text
EntryReconciliationCommand + source_state
→ EntryPackageRequest
    (strategy_instance_id, trade_cycle_id, ticker,
     desired_entry: EntryPackageWireDesiredEntry | None,
     risk_multiplier = source_state.risk_multiplier)
→ AbiEntryPackagePort.send            (exactly one call)
→ EntryPackageApplied   → EntryAppliedConfirmation
   EntryPackageAbsent    → EntryAbsentConfirmation
   EntryPackagePublicError (returned result)
                          → EntryReconciliationExecutionError(public_error=result)
   AbiEntryPackageTimeout / AbiEntryPackageNetworkFailure /
   AbiEntryPackageProtocolError (raised exceptions)
                          → raise EntryReconciliationExecutionError(...) from <exc>
```

The bridge:

- reads `risk_multiplier` from `source_state` (never from the command);
- maps `DesiredEntry` → `EntryPackageWireDesiredEntry` for a present package and
  `None` for an absent package;
- maps `EntryPackageApplied.applied_desired_entry` (`EntryPackageWireDesiredEntry`)
  back into the domain `DesiredEntry` for the confirmation;
- calls the existing `AbiEntryPackagePort.send` exactly once;
- distinguishes two different unconfirmed-outcome shapes from the existing
  `AbiEntryPackagePort.send` call:
  - `EntryPackagePublicError` is a typed dataclass **result value** returned by
    `send`, not a raised exception. The bridge constructs
    `EntryReconciliationExecutionError(public_error=result)` from that value.
    Nothing was caught or re-raised in this path, so there is no `__cause__`
    chain and none is required.
  - `AbiEntryPackageTimeout`, `AbiEntryPackageNetworkFailure`, and
    `AbiEntryPackageProtocolError` are **raised exceptions** from `send`. The
    bridge catches each and raises `EntryReconciliationExecutionError(...) from
    <original exception>`, preserving the original exception as `__cause__` so
    the caller can observe the underlying reason.

It explicitly does **not** own an HTTP transport, URL encoding, timeout/redirect
configuration, the keyed mutex, repository load/save, retry, reconciliation
decisions, or state mutation. It is covered by ordinary typed unit/translation
tests against a fake `AbiEntryPackagePort`, not fake-HTTP tests — there is no
HTTP behavior in this component to contract-test.

**Rationale:** The ABI entry-package HTTP client already exists and is
contract-tested. Reimplementing HTTP ownership in the bridge would duplicate the
transport seam and split timeout/redirect configuration across two components.
A pure translator keeps the bridge testable without HTTP fixtures.

**Alternative considered:** Have the bridge call ABI over its own HTTP client.
Rejected — it would create a second entry-package HTTP transport and break the
single-client invariant the `abi-entry-package-client` capability established.

### accepted_risk_multiplier removal is a breaking DTO change

`runtime-abi-entry-reconciliation-master-plan.md` §4 defines `risk_multiplier`
as an operational value Runtime sends to ABI one-way; ABI does not return or
reconfirm it. The archived `abi-entry-package-client-v1` DTO
`EntryPackageApplied.accepted_risk_multiplier` contradicts that rule. `I4c`
removes the field from:

- `EntryPackageApplied` dataclass;
- `_APPLIED_FIELDS` in `entry_package_codec.py`;
- the applied-success decode path;
- fake-ABI fixtures and contract tests;
- the OpenAPI-conformance test (the applied success union no longer includes
  `accepted_risk_multiplier`).

After `I4c`, the strict decoder rejects an ABI response that still carries
`accepted_risk_multiplier` as an unknown field. `I4c` does not modify or own
the ABI repository, but the ABI-side contract-only cleanup removing
`accepted_risk_multiplier` from the entry-package "applied" response —
including the sibling ABI OpenAPI document — is an external baseline
prerequisite before task 6.4 (the OpenAPI-conformance test) and before final
`I4c` verification/sign-off: task 6.4 reads that document and cannot pass
against a stale one that still advertises the field. ABI's own production
deployment alignment (no longer actually returning the field at runtime)
remains a separate external prerequisite before `I4d` composes the client
into production; `I4c` does not block on runtime deployment because the
client remains unconnected.

**Rationale:** Keeping the echo would propagate a known contract mismatch into
production composition. Removing it now, while the client is still unconnected,
is the lowest-risk moment.

### Bounded, non-retried, no-redirect transport for all three HTTP adapters

Each HTTP adapter mirrors the existing `HttpxAbiEntryPackageAdapter` transport
discipline:

- `httpx.Client(timeout=<finite positive>, follow_redirects=False,
  transport=httpx.HTTPTransport(retries=0))`;
- exactly one HTTP request per port call;
- no automatic retry, no redirect following;
- redirects and undocumented statuses become protocol errors.

**Rationale:** Live V1 has no idempotency or ambiguous-outcome recovery
contract. Retrying a state-changing or lookup request inside the client would
invent reliability semantics that have not been approved.

### Shared codec helpers are local to the three new adapters

The existing `entry_package_codec.py` helpers (`_closed_object`,
`_require_exact_fields`, `_require_json_content_type`,
`_reject_duplicate_object_fields`, `_encode_opaque_path_segment`) are private to
the ABI entry-package client. `I4c` does not refactor them into a shared module
used by the existing client. The three new adapters may share local codec
helpers among themselves (for example a small `runtime/shared/http_codec.py`
used only by the three new adapters) provided that does not expand scope into the
existing ABI entry-package client.

**Rationale:** Refactoring the archived, contract-tested ABI entry-package
client would broaden `I4c` scope and risk regressing a shipped seam. Keeping new
helpers local to the new adapters preserves the archived client's stability.

### request_id is preserved in exceptions, not journaled in I4c

`StrategyEngineProjectionPublicError` (and `StrategyEngineMarketStreamNotFound`)
preserve the Engine `request_id` as an exception attribute. `I4c` does not emit
journal entries or metrics for adapter outcomes; operational journaling is a
later increment. Preserving `request_id` now ensures a future journaling layer
has the correlation value without re-decoding the response.

## Risks / Trade-offs

- [A timeout can follow successful Engine or ABI processing] → Surface a typed
  timeout and leave recovery to a later approved change; do not retry or claim
  success. The keyed critical section in `I4d` will release on the propagated
  exception.
- [Strict decoding rejects additive external fields] → Intentional contract-drift
  detection; all V1 DTOs are closed, and an additive field is a deliberate
  contract change requiring an OpenSpec update.
- [The `accepted_risk_multiplier` removal breaks the archived client DTO] →
  Intentional and bounded: the field contradicts the master plan, the client is
  unconnected, and ABI alignment is tracked as an external prerequisite.
- [No ABI open-position OpenAPI conformance test] → Accepted for `I4c`; fake-HTTP
  contract tests cover the Runtime-side decoder, and conformance is added when
  ABI publishes the authoritative document.
- [Opaque diagnostics means Runtime cannot detect an Engine diagnostics schema
  change] → Accepted by the existing `use-case-router` contract; the router is
  explicitly forbidden from interpreting diagnostics fields.
- [Three new adapters duplicate transport/codec patterns] → Accepted to avoid
  refactoring the archived ABI entry-package client; local sharing among the
  three new adapters is permitted.

## Migration Plan

1. Add the granular Engine failure taxonomy, the ABI open-position failure
   extensions, and the bridge execution error as new typed exception modules
   without wiring them into the orchestrator or router.
2. Add closed wire DTOs and codecs for the three HTTP adapters.
3. Add the three HTTP adapter implementations with bounded non-retried transport.
4. Add the entry-execution bridge implementation.
5. Remove `accepted_risk_multiplier` from the ABI entry-package client DTO,
   codec, fixtures, and conformance test.
6. Add fake-HTTP contract tests for the three adapters and unit/translation
   tests for the bridge.
7. Deploying this change alone alters no active Runtime request flow because no
   production composition or reconciliation wiring is part of the change.
8. Rollback removes the new adapter, bridge, DTO, codec, error, and test modules
   and restores `accepted_risk_multiplier`; no state, data, ABI, or exchange
   migration is required.

## Open Questions

None that block `I4c`. The ABI open-position public-error envelope's exact
`details` structure (what ABI will publish for `400`/`422`) is not yet fixed by
ABI; the Runtime decoder accepts the closed ABI-style nested `{error: {code,
message, details}}` envelope shape already used by the ABI entry-package
endpoint, treating `details` as an opaque JSON value until ABI publishes a
stricter schema. Unlike the Strategy Engine's flat `{error, message, details,
request_id}` envelope, this envelope is nested under a single top-level
`error` key and carries no `request_id`. This does not block `I4c` because the
decoder fails closed on any malformed envelope rather than inventing ABI's
validation rules.
