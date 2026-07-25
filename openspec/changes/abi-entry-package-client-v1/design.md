## Context

Runtime currently stops after producing a validated live-entry projection and
has no production client for the next Runtime → ABI seam. The sibling ABI
service already exposes and implements:

```text
PUT /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/entry-package
```

The approved ABI OpenSpec and OpenAPI are the wire-contract authority.
`risk_multiplier` is strategy-instance configuration and is therefore a
required positive exact-decimal string whether `desired_entry` is present or
null.

Runtime owns `strategy_instance_id`, `trade_cycle_id`, ticker, `DesiredEntry`,
and `risk_multiplier`; ABI owns application of the indivisible entry,
initial-stop, and initial-take package and returns either an applied or absent
acknowledgement.

This change defines only the consumer-side contract. In particular, it does
not decide when to send a package, update `CurrentTradeCycle`, persist an
acknowledgement, or connect the client to `StrategyRuntimeOrchestrator`.

## Goals / Non-Goals

**Goals:**

- Mirror the approved ABI route, request shape, response union, and public
  error taxonomy.
- Provide a scalar Runtime outbound port and a production HTTP adapter.
- Preserve opaque Runtime-owned values and exact-decimal text across the wire.
- Decode every ABI response as a closed, typed DTO and verify ownership binding.
- Distinguish public ABI rejections, timeout, network failure, and invalid ABI
  protocol responses.
- Make one bounded, non-retried HTTP call and fail closed unless a valid bound
  acknowledgement is received.
- Verify the adapter with a fake ABI and against the authoritative ABI OpenAPI
  artifact.

**Non-Goals:**

- No entry reconciliation or `NO_OP`/`APPLY`/`REPLACE`/`CANCEL` decision.
- No creation, replacement, freezing, or persistence of `CurrentTradeCycle`.
- No Runtime state mutation or acknowledgement application.
- No orchestrator or production composition wiring.
- No idempotency, retry, lookup recovery, ambiguous-outcome state, or durable
  pending command.
- No ABI, sizing, risk-policy, executor, or exchange implementation change.
- No new validation or normalization of Runtime-owned values beyond the
  approved wire contract.

## Decisions

### Use a scalar port with transport-free DTOs

The client boundary will expose one operation conceptually shaped as:

```text
AbiEntryPackagePort.send(EntryPackageRequest)
  -> EntryPackageApplied
   | EntryPackageAbsent
   | PublicAbiError
```

`EntryPackageRequest` contains the two path identifiers plus the exact three
body fields. Construction enforces the closed request shape:

```text
desired_entry != null + risk_multiplier != null
desired_entry = null + risk_multiplier != null
```

`risk_multiplier = null` is not representable by the port DTO and is invalid
regardless of `desired_entry`.

The port and its DTOs contain no HTTP client types. Public ABI errors are typed
results because they are valid, decoded ABI responses. Timeout, network
failure, and invalid ABI response are typed client exceptions because no valid
ABI result was obtained.

**Rationale:** Callers can exhaustively handle every public ABI outcome without
coupling application code to HTTP, while transport/protocol failures cannot be
mistaken for a business acknowledgement.

**Alternative considered:** Return `None`, booleans, or a generic exception for
all failures. This would suppress the ABI error taxonomy and make absent,
rejected, and unconfirmed outcomes ambiguous.

### Keep wire DTOs separate from richer Runtime domain models

The ABI-facing `DesiredEntry` DTO has exactly six fields and follows the ABI
wire constraints:

```text
side: long | short
source_plan_bar_open_time_ms: JSON integer
planned_entry_price: exact-decimal string
initial_stop_price: exact-decimal string
initial_take_price: positive exact-decimal string
locked_exit_profile: string
```

Closed response objects reject missing and unknown fields. JSON booleans are
not accepted as integers. The wire decoder does not add timestamp ranges,
profile content/length rules, price ordering, or positivity for planned entry
or initial stop. Mapping from Runtime domain objects is explicit rather than
reusing a model whose constructor may impose stronger internal invariants.

**Rationale:** The consumer must accept exactly the approved ABI response
language. Reusing a richer domain model at the JSON boundary could silently
narrow the wire contract.

**Alternative considered:** Serialize and deserialize the existing Runtime
`DesiredEntry` directly. Its internal invariants and normalization policy are
not the normative ABI response schema.

### Preserve exact-decimal lexemes as strings

All three desired-entry prices, required `risk_multiplier`,
`accepted_risk_multiplier`, and `calculated_quantity` remain strings from DTO
construction through JSON encoding/decoding. Validation may inspect decimal
text without binary floating-point conversion but must retain the accepted
lexeme unchanged. `initial_take_price` and `risk_multiplier` must be
positive; `accepted_risk_multiplier` must be positive; the other decimal
fields only need to be finite exact-decimal text.

**Rationale:** ABI sizing and exchange normalization own numeric
interpretation. Runtime must not introduce rounding or textual normalization at
this transport seam.

**Alternative considered:** Convert through `float` or JSON numbers. That loses
decimal precision and violates the established ABI schema.

### Build the exact route from independently encoded path segments

The adapter sends `PUT` to the versioned route and JSON-encodes exactly
`ticker`, `desired_entry`, and `risk_multiplier`. It percent-encodes each
identifier as one UTF-8 path segment while preserving its decoded value,
including slashes, whitespace, Unicode, percent characters, and dot-only
segments. It does not canonicalize case, trim, derive, or otherwise rewrite
identifiers or ticker.

The adapter sends `Content-Type: application/json` and accepts only JSON
responses compatible with the ABI UTF-8 response contract.

**Rationale:** Direct string interpolation can turn opaque identifiers into
additional path segments or allow URL dot-segment normalization.

**Alternative considered:** Require UUID-shaped or pre-escaped identifiers.
ABI explicitly treats these Runtime-owned values as opaque non-empty strings.

### Strictly discriminate and bind success acknowledgements

Only HTTP `200` can produce a success result. Its closed JSON body must match
exactly one of:

```text
EntryPackageApplied
├── strategy_instance_id
├── trade_cycle_id
├── status = entry_package_applied
├── applied_desired_entry
├── accepted_risk_multiplier
└── calculated_quantity
```

```text
EntryPackageAbsent
├── strategy_instance_id
├── trade_cycle_id
└── status = entry_package_absent
```

For both variants, returned `strategy_instance_id` and `trade_cycle_id` must
exactly equal the unencoded values from the originating request. A malformed
body, unknown field, wrong type, invalid decimal, unknown success status, or
identity mismatch becomes `AbiEntryPackageProtocolError`; no partial object or
fallback success is returned.

The client does not infer exchange actions from a success DTO and does not
apply it to Runtime state.

**Rationale:** A structurally valid acknowledgement for a different ownership
pair is not confirmation of the requested command.

**Alternative considered:** Trust status alone or ignore response identities.
That would permit a misrouted or stale response to be treated as success.

### Decode the four public ABI errors without suppression

The only public error mappings are:

| HTTP | Public result |
|---:|---|
| `400` | `malformed_json` with non-empty `message` |
| `415` | `unsupported_media_type` with non-empty `message` |
| `422` | `validation_failed` with non-empty `message` and non-empty closed `details` |
| `500` | `internal_error` with non-empty `message` |

Each body is a closed `{"error": ...}` envelope. Validation details preserve
the ABI-provided `path` and `message`; `details` must be omitted for the other
three codes. A status/code mismatch, malformed envelope, missing/extra field,
or any undocumented HTTP status is an
`AbiEntryPackageProtocolError`, not a public error result.

**Rationale:** Public rejections are actionable contract outcomes, while an
undecodable or undocumented response leaves Runtime without a trustworthy
result.

**Alternative considered:** Collapse every non-`2xx` into one availability
error. That discards the approved ABI taxonomy and validation diagnostics.

### Perform one bounded attempt and fail closed

The HTTP adapter performs exactly one request with a required finite positive
timeout. Automatic retries and redirect following are disabled. A timeout is
reported as `AbiEntryPackageTimeout`; another connection, DNS, TLS, or network
transport failure is reported as `AbiEntryPackageNetworkFailure`.

Any `1xx`, redirect, undocumented status, invalid content type, invalid JSON,
or schema-invalid response is reported as
`AbiEntryPackageProtocolError`. None of these cases returns an applied or
absent result.

**Rationale:** Live V1 deliberately has no idempotency or ambiguous-outcome
recovery contract. Retrying a state-changing request inside the client would
invent reliability semantics that have not been approved.

**Alternative considered:** Retry timeouts and transient statuses. Without an
idempotency/recovery contract, a timeout may have occurred after ABI applied
the package.

### Verify against a fake ABI and the authoritative OpenAPI

Contract tests use a controllable fake HTTP ABI to inspect the raw request and
emit every success, public-error, timeout, network, and malformed-response
case. Separate conformance verification reads the approved sibling ABI OpenAPI
document and asserts the exact method, route, mandatory non-null
`risk_multiplier`, nullable `desired_entry`, response union, closed-object
rules, decimal formats, and four error mappings used by the Runtime decoder.

The OpenAPI file is a development/CI contract input, not a Runtime production
dependency. Missing or divergent authoritative input fails conformance
verification rather than silently falling back to a locally weakened schema.

**Rationale:** Fake-server tests prove adapter behavior; OpenAPI checks detect
contract drift between repositories.

**Alternative considered:** Test only hand-written fixtures. They can remain
internally consistent while drifting from the implemented ABI contract.

## Risks / Trade-offs

- [A timeout can follow successful ABI application] → Surface a typed timeout
  and leave recovery/reconciliation to a later approved change; do not retry or
  claim success.
- [A sibling OpenAPI dependency complicates isolated CI] → Keep it out of
  production code and make its path an explicit verification input.
- [Strict decoding rejects additive ABI fields] → Treat this as intentional
  contract drift detection because all V1 DTOs are closed.
- [Opaque identifiers include URL-sensitive values] → Test raw encoded paths,
  decoded equality, and dot-only segments with the fake ABI.
- [Runtime domain invariants differ from ABI wire invariants] → Keep wire DTOs
  separate and test that the client adds no constraints absent from OpenAPI.

## Migration Plan

1. Add the transport-free DTOs, public result union, typed client failures, and
   outbound port without wiring them into the orchestrator.
2. Add the HTTP adapter with explicit base URL and bounded timeout
   configuration.
3. Add fake-ABI and OpenAPI conformance tests.
4. Deploying this layer alone changes no active Runtime request flow because no
   production composition or reconciliation wiring is part of the change.
5. Rollback removes the unused client layer and its tests; no state, data, ABI,
   or exchange migration is required.

## Open Questions

None for the scoped client-contract layer.
