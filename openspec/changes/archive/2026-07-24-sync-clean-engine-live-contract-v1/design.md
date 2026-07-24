## Context

Strategy Runtime currently serializes its derived `strategy_instance_id` into
Engine request field `instance_id` and expects Engine to echo five request
bindings in both projection responses. The cleaned Strategy Engine live
contract no longer accepts Runtime identity and returns calculation payloads
only.

The Runtime call is synchronous and scalar. The router already owns the
`PositionResolvedStrategyInstance` before invoking Engine and can therefore
attach the returned calculation to that exact local object without a
wire-level correlation field.

## Goals / Non-Goals

**Goals:**

- Remove only Engine-facing `instance_id` from both request DTOs.
- Model live-entry response as `plans_by_side`.
- Model open-trade response as the three calculation objects only.
- Remove response echo validation and its dedicated error.
- Reject old echo-bearing response payloads during strict DTO construction.
- Preserve Runtime and ABI strategy-instance identity everywhere else.
- Keep OpenSpec, System Plans, code, and tests synchronized.

**Non-Goals:**

- No flat-versus-nested HTTP payload decision.
- No recipe, routing, open-trade receipt, or ABI contract change.
- No removal of `strategy_instance_id` from Runtime processing or state.
- No production HTTP Engine client implementation.
- No lifecycle or state-application work.

## Decisions

### Correlate synchronously through local call context

The binding flow is:

```text
PositionResolvedStrategyInstance
→ scalar Engine port call
→ calculation-only response
→ projected object whose source is the same Runtime instance
```

No Engine response field participates in Runtime identity. The existing
pre-call invariant among processing unit, deployment, and runtime state remains
in force.

**Rationale:** A scalar synchronous call already provides unambiguous
correlation. Sending Runtime identity to a pure calculator adds coupling without
improving correctness.

### Keep calculation inputs except Runtime identity

Both request DTOs retain strategy ID, raw specification, ticker, base
timeframe, and exact target bar. Open-trade additionally retains its existing
entry recipe and execution facts. Only `instance_id` is removed.

**Rationale:** Those values are calculation inputs; `strategy_instance_id` is
Runtime/ABI ownership metadata.

### Consume the Engine result shapes directly

Live-entry response contains only:

```text
plans_by_side
```

The router reads `long` and `short` from that mapping when constructing the
unchanged `EntryRecipe`.

Open-trade response contains only:

```text
desired_protection
close_signal
diagnostics
```

The existing `PositionManagementRecipe` mapping is unchanged.

### Make the DTO boundary reject old responses

Response DTO constructors accept only the calculation fields. Passing any old
echo field such as `strategy_id`, `instance_id`, `ticker`,
`base_timeframe`, or `target_bar_open_time_ms` fails as an unknown constructor
argument. The eventual HTTP adapter must preserve the same strict unknown-field
policy when decoding JSON.

**Rationale:** Silent compatibility with the obsolete response shape would hide
deployment skew between Runtime and Engine.

### Remove response binding errors, retain local binding errors

`EngineResponseBindingError` and `_validate_echo()` are removed.
`StrategyInstanceBindingError`, `StrategyEngineProjectionUnavailable`, and
`OpenTradeContextUnavailable` remain distinct and unchanged.

## Risks / Trade-offs

- [An asynchronous Engine transport is introduced later] → Define an explicit
  correlation contract then; do not retain obsolete synchronous echoes now.
- [A stale Engine still returns echoes] → Strict DTO decoding rejects the
  payload instead of accepting mixed contract versions.
- [`plans_by_side` contains unexpected keys] → Runtime consumes only `long` and
  `short`; Engine owns its result-map vocabulary and recipe semantics remain
  unchanged.

## Migration Plan

Deploy the cleaned Engine contract and this Runtime DTO update as one compatible
service rollout. Rollback requires reverting both sides to the previous
echo-bearing contract.

## Open Questions

None.
