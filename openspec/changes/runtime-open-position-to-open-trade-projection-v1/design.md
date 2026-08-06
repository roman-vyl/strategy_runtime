## Context

The prior change made `position_open=true` fail closed unconditionally,
before any Engine call. Everything needed to go further already exists and
is unchanged by this design: the first-fill transition, the open-trade
Engine port and its HTTP adapter, and the frozen registered-spec snapshot
on Runtime state.

## Goals / Non-Goals

**Goals:** apply the first-fill transition and persist it before routing;
route an open position to Strategy Engine's open-trade endpoint from that
frozen context.

**Non-Goals:** applying the Engine response; cold-restart recovery or
lost-trade-cycle search; any persistent Runtime state. V1 operates only on
the in-memory state of the current process — a position without a live
`CurrentTradeCycle` is not this change's concern.

## Decisions

**Freeze belongs to the orchestrator, not the router.** The router is a
pure request/response mapper and applies no state transitions.
`StrategyRuntimeOrchestrator` already owns the repository and the keyed
critical section, so it applies the existing first-fill transition and
saves a changed result there, before calling the router — under the same
mutex already held for the whole call, serializing against the ABI
first-fill callback path via that transition's existing idempotency and
conflict rules. No new transition, invariant, or coordination primitive is
introduced. A missing current trade cycle at freeze time surfaces as the
typed invariant failure the transition already raises for it, not an
incidental exception.

**Save happens before the Engine call.** A first fill is an already
confirmed external fact; an Engine failure afterward must not un-persist
it. Ordering, not new machinery, provides this guarantee.

**The router requires a frozen entry context; it does not create one.**
It reads the frozen context already present on the resolved state and
builds the open-trade request from the registered spec snapshot plus that
context — not from the live processing unit's deployment, never from
`average_entry_price`. A missing frozen context still fails closed with
the existing `OpenTradeContextUnavailable`, independent of what the
orchestrator guarantees upstream.

**The Engine response is wrapped, not interpreted.** It fits the existing
open-trade projected type unchanged, with no field translation beyond that
wrapping. Applying the response is deliberately deferred to a later
change.

## Risks / Trade-offs

- [The freeze step adds a repository write on a path that previously never
  reached the repository] → Intentional: it is the persisted record of an
  already-confirmed fill, independent of downstream Engine outcome.
