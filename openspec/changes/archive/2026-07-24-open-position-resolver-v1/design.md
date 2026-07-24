## Context

`StrategyRuntimeOrchestrator.process(...)` handles one
`StrategyBarProcessingUnit`. After repository get-or-create, it passes the
single returned `StrategyInstanceRuntimeState` to `OpenPositionResolver`.

Local Runtime state cannot prove whether ABI currently has an associated open
position, so the lookup is performed for every invocation.

## Goals / Non-Goals

**Goals:**

- Define a scalar resolver boundary.
- Send only strategy-instance identity to ABI exactly once.
- Validate exact open-position response invariants.
- Preserve decimal values without binary-float conversion.
- Return one transient resolved-state view.
- Propagate typed adapter failures without masking programming errors.

**Non-Goals:**

- No use-case routing or Strategy Engine call.
- No recipe or trade-cycle lifecycle changes.
- No repository write-back.
- No ABI endpoint or HTTP implementation.
- No exchange identifiers, protection data, side, or quantity.

## Decisions

### Use a scalar Runtime boundary

The implemented call sequence is:

```text
StrategyRuntimeOrchestrator.process(unit)
→ state_repository.get_or_create(request)
→ open_position_resolver.resolve(state)
→ use_case_router.route(PositionResolvedStrategyInstance(unit, resolved))
```

The resolver port is:

```python
class OpenPositionResolverPort(Protocol):
    def resolve(
        self,
        state: StrategyInstanceRuntimeState,
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        ...
```

Fan-out is owned by the upstream utility orchestrator. This semantic operation
therefore needs no collection cardinality, ordering, or partial-result contract.

### Send only strategy-instance identity

For the input state, the resolver constructs exactly one:

```text
OpenPositionLookupRequest
- strategy_instance_id
```

It does not filter based on current trade cycle, recipe presence, or a local
searching/open interpretation.

### Keep the ABI response narrow and strict

```text
OpenPositionLookupResponse
- position_open: exact bool
- entry_bar_open_time_ms: int | null
- executed_entry_price: DecimalText | null
```

`position_open` accepts only the Python boolean type. Integer `0` and `1`,
strings, and null are invalid protocol values.

For `position_open = false`, both execution facts must be absent. For
`position_open = true`, both must be present and the entry bar must be
non-negative. Executed price is normalized as decimal text without a
binary-float conversion.

### Return transient enrichment without mutation

The result retains the exact input aggregate and adds only:

```text
PositionResolvedStrategyInstanceRuntimeState
- runtime_state
- position_open
- entry_bar_open_time_ms
- executed_entry_price
```

The resolver does not call a repository writer, mutate the aggregate, select an
Engine path, or interpret lifecycle.

### Classify failures at the ABI adapter boundary

An ABI adapter must classify:

- network, timeout, and HTTP availability failures as
  `OpenPositionLookupUnavailable`;
- malformed JSON, invalid types, missing fields, or contradictory response
  combinations as `OpenPositionLookupProtocolError`.

The resolver propagates these typed failures unchanged. It has no blanket
exception handler, so programming defects are not mislabeled as availability
failures and `position_open = false` is never fabricated.

The production ABI adapter is outside this change; tests use port fakes that
raise the required typed failures.

## Dependency Rules

The resolver may depend on Runtime state models, resolver-owned models and
errors, and `AbiOpenPositionLookupPort`. It must not depend on Engine clients,
router implementation, repository adapters, FastAPI handlers, or exchange SDKs.

## Risks / Trade-offs

- [A transport adapter misclassifies an error] → Classification is an explicit
  adapter contract and is verified at the resolver port with typed fakes until
  the production adapter exists.
- [Position facts are transient] → State application remains an explicit later
  capability rather than an implicit resolver side effect.

## Migration Plan

No persisted data migration is involved.

## Open Questions

None.
