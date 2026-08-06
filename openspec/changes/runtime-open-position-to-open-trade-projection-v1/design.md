## Context

`runtime-abi-open-position-trade-cycle-alignment-v1` (archived) made the ABI
open-position lookup trade-cycle-conditional and left
`StrategyUseCaseRouter` raising `OpenTradeContextUnavailable`
unconditionally for `position_open=true`, before touching
`current_trade_cycle`. Consequence: `resolved.position_open=true` implies
`resolved.runtime_state.current_trade_cycle is not None` (ABI is only ever
called with an existing `trade_cycle_id`), and
`resolved.first_fill_at_ms`/`.average_entry_price` are guaranteed non-null
by `OpenPositionLookupResponse`'s own invariant. This change relies on both
facts instead of re-deriving them.

The pieces this change wires together already exist and are unchanged:
`apply_first_fill` (freeze transition), `AbiExecutionEventOrchestrator`
(the callback path that also calls it), `OpenTradeProjectionRequest`/
`OpenTradeProjectionResponse`, and `HttpxStrategyEngineOpenTradeAdapter`
wired into `bootstrap/application.py`. `tests/unit/runtime/
test_semantic_pipeline.py` already carries an `OpenEngine` test double for
this exact call, unused until now.

## Goals / Non-Goals

**Goals:**
- Freeze first-fill context from the closed-bar path when ABI reports
  `position_open=true` and no callback has frozen it yet.
- Call Strategy Engine's open-trade endpoint with a request built from the
  registered spec snapshot and the frozen context.
- Reach the existing `OpenTradeProjectionUnsupportedError` boundary with a
  real Engine response instead of never getting there.

**Non-Goals:**
- Applying `desired_protection`, `close_signal`, or diagnostics.
- Cold-restart recovery, lost-`CurrentTradeCycle` search, persistent state.
- Changing the ABI open-position contract, the Engine open-trade contract,
  or `average_entry_price`'s reach (stays ABI/Runtime-only).

## Decisions

**Freeze site: `StrategyRuntimeOrchestrator`, not the router.**
The router stays a pure request/response mapper (existing
`use-case-router` requirement: "keep state application and execution
outside the router"). `StrategyRuntimeOrchestrator.process(...)` already
owns the keyed critical section and the repository; it freezes and saves
between `resolver.resolve(...)` and `router.route(...)`:

```
resolved = self._open_position_resolver.resolve(state)
if resolved.position_open:
    resolved = self._ensure_first_fill_frozen(resolved)
projection = self._use_case_router.route(
    PositionResolvedStrategyInstance(unit, resolved)
)
```

**Freeze implementation: call `apply_first_fill` unconditionally, trust its
own no-op/conflict handling.** Mirrors `AbiExecutionEventOrchestrator
.process(...)`, which calls `apply_first_fill` and only compares
`resulting_state is state` to decide whether to save — it does not
pre-check `frozen_entry_context`. `_ensure_first_fill_frozen` does the
same:

```
def _ensure_first_fill_frozen(self, resolved):
    state = resolved.runtime_state
    trade_cycle_id = state.current_trade_cycle.trade_cycle_id
    resulting_state = apply_first_fill(state, trade_cycle_id, resolved.first_fill_at_ms)
    if resulting_state is state:
        return resolved
    saved_state = self._state_repository.save(resulting_state)
    return replace(resolved, runtime_state=saved_state)
```

`state.current_trade_cycle` is read unguarded: the invariant above
guarantees it is not `None` whenever `resolved.position_open` is `true`.
If that invariant is ever violated, this raises `AttributeError` — a loud,
immediate failure, not a silent fallback. No new invariant check
duplicates what `apply_first_fill` already enforces
(`FirstFillInvariantError` for a missing current cycle, a no-op for an
identical repeat, a fail-closed raise for a conflicting timestamp). Save
happens before the Engine call, so an Engine failure afterward never
un-persists the freeze — this is deliberate (see proposal "Why").

Concurrency: this runs inside the same keyed mutex
`StrategyRuntimeOrchestrator` already holds for the whole `process(...)`
call, so it serializes against the ABI-callback path
(`AbiExecutionEventOrchestrator`) exactly as `apply_first_fill`'s own
idempotency/conflict rules already describe (see `first-fill-transition`
spec) — no new coordination primitive.

**Router: require a frozen context, don't freeze one.** After
`_validate_instance_binding`, for `position_open=true` the router reads
`resolved.runtime_state.current_trade_cycle.frozen_entry_context`
(guarded — `current_trade_cycle` can be inspected without the orchestrator
guarantee here, since this path is also exercised directly in router unit
tests that bypass the orchestrator). If unset, raise the existing
`OpenTradeContextUnavailable` — this is the router's own defense-in-depth,
independent of whatever the orchestrator has already guaranteed upstream.
If set, build:

```
OpenTradeProjectionRequest(
    strategy_id=runtime_state.strategy_id,
    raw_spec=snapshot.raw_spec,
    ticker=snapshot.instrument,
    base_timeframe=snapshot.base_timeframe,
    target_bar_open_time_ms=unit.committed_bar.open_time_ms,
    desired_entry=frozen.desired_entry,
    entry_bar_open_time_ms=frozen.entry_bar_open_time_ms,
)
```

where `snapshot = runtime_state.registered_spec_snapshot` — the frozen
registration snapshot, not the live `unit.deployment`, matching how the
frozen entry context is itself sourced from registered state rather than
the current processing unit. `average_entry_price` is not read anywhere in
the router (unchanged from the prior change).

**Result mapping: wrap the Engine response in the existing
`PositionManagementRecipe`.** `OpenTradeProjectedStrategyInstance
.position_management_recipe: PositionManagementRecipe` predates this
change and has the same three fields as `OpenTradeProjectionResponse`
(`desired_protection`, `close_signal`, `diagnostics`). The router
constructs `PositionManagementRecipe(**response.__dict__ shape)` field by
field and returns `OpenTradeProjectedStrategyInstance(source=item,
position_management_recipe=recipe)`. No model changes.

**Orchestrator post-projection boundary: unchanged code, now reachable.**
`OpenTradeProjectionUnsupportedError` for an exact
`OpenTradeProjectedStrategyInstance` stays as-is — it was already correct
for "stop after a successful projection"; it just never fired for a real
projection before this change.

## Risks / Trade-offs

- [Existing router-level unit tests construct `position_open=true` states
  without a frozen context, bypassing the orchestrator's freeze step] →
  Router's own `OpenTradeContextUnavailable` guard keeps those tests valid
  as a defense-in-depth assertion, not a resolver/orchestrator assertion;
  `test_router_fails_closed_for_open_position_even_with_complete_context`
  is retargeted to this guard.
- [`_ensure_first_fill_frozen` always calls the repository's `save` on the
  first freeze, adding a write on the open-trade path that never happened
  before] → Matches criterion "Engine failure does not roll back an
  already-saved first-fill context"; the write is the intended new
  behavior, not an accidental side effect.
