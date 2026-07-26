# Runtime ↔ ABI entry reconciliation master plan

Status: discussion-approved high-level plan for the second half of the Runtime live-entry pipeline. This document is not an OpenSpec change and does not yet authorize implementation.

The live-entry behavior in this plan starts when Runtime owns one typed Strategy
Engine projection result and ends when ABI execution events have updated the
Runtime-owned repository state. Its serialization boundary begins earlier:
the top-level closed-bar orchestrator acquires the keyed mutex before loading
state and retains it through position lookup, Engine projection, live-entry
application, and save.

## 1. Scope and starting boundary

The implemented first half of the closed-bar pipeline currently ends with one
of two typed objects:

```text
LiveEntryProjectedStrategyInstance
OpenTradeProjectedStrategyInstance
```

This plan covers only the live-entry branch:

```text
LiveEntryProjectedStrategyInstance
-> desired entry reconciliation
-> ABI attached entry package
-> ABI acknowledgement
-> CurrentTradeCycle
-> ABI partial/full fill webhooks
-> Runtime state transition
```

The plan does not redesign how either projection is calculated. It does define
the caller-owned critical section around that calculation so no execution
webhook can invalidate the state between projection and application.

The open-trade/position-management reconciliation branch will be designed
separately after this entry branch is settled. Completing the entry/fill
increments in this plan does not by itself establish full Live V1 readiness:
after the first fill, the next authoritative position lookup selects the
open-trade branch, which remains explicitly unsupported until that later work.

## 2. Two independent Runtime entry points

Runtime has two independent external inputs.

### Closed-bar input

```text
MDS committed-bar webhook
-> closed-bar strategy cycle
-> Engine projection
-> entry reconciliation
```

Its purpose is to calculate what the strategy wants now and reconcile that desired state with ABI.

### Execution-event input

```text
ABI execution webhook
-> ABI execution-event use case
-> Runtime state mutation
```

Its purpose is to record what actually happened on the exchange.

An ABI webhook does not resume, interrupt, or enter the middle of a previous MDS request. It starts a separate Runtime use case.

## 3. Orchestrator structure and serialization ownership

The existing `StrategyRuntimeOrchestrator` remains the single top-level
coordinator for the closed-bar Runtime use case. The next change extends that
orchestrator in place; it does not introduce another top-level closed-bar
coordinator or a separate projection coordinator.

`EntryReconciliationOrchestrator` is already implemented as the nested
live-entry application operation. The upper workflow calls that existing
component rather than creating it as part of the closed-bar extension.

```text
StrategyCycleHandoffBoundary.dispatch(unit)
→ StrategyRuntimeOrchestrator.process(unit)
    → acquire keyed mutex(strategy_instance_id)
    → load or create current StrategyInstanceRuntimeState
    → resolve authoritative ABI position facts
    → obtain the typed Strategy Engine projection
    → branch on the projection type
        ├── LiveEntryProjectedStrategyInstance
        │   → existing EntryReconciliationOrchestrator.execute(projection)
        │   → save replacement state when required
        └── OpenTradeProjectedStrategyInstance
            → fail explicitly as unsupported until separately designed
    → release mutex
```

`StrategyRuntimeOrchestrator` will own the complete closed-bar critical section.
The implemented nested `EntryReconciliationOrchestrator` will run inside that
already-open critical section and does not acquire the keyed mutex, reload the
aggregate, or save repository state independently.

Realtime ABI callbacks start a separate Runtime use case:

```text
ABI execution webhook
-> AbiExecutionEventOrchestrator
   -> acquire the same keyed mutex
   -> load fresh StrategyInstanceRuntimeState
   -> apply the execution event
   -> save
   -> release mutex
```

The two top-level paths meet through both the shared keyed-mutex registry and
the Runtime-owned `StrategyInstanceRuntimeStateRepository`.

## 4. Strategy-instance aggregate

`CurrentTradeCycle` is nested inside the long-lived strategy-instance aggregate:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── strategy_id
├── registered_spec_snapshot
├── risk_multiplier
└── current_trade_cycle: CurrentTradeCycle | null
```

`registered_spec_snapshot` remains the existing immutable Runtime snapshot
containing:

```text
instrument
base_timeframe
raw_spec
source_path
```

`risk_multiplier` belongs only to the Runtime-owned strategy-instance state. A
newly created state receives `"1"`; the value is not sourced from deployment
configuration, registered snapshots, Engine projections, trade-cycle models, or
strategy identity. When an outbound ABI operation requires this operational
value, the ABI adapter reads it directly from the loaded state and sends it
one-way to ABI. ABI responses do not contain or acknowledge it.

`current_trade_cycle = null` means that Runtime owns no current trade cycle or
acknowledged entry package for the instance. This value does not replace an ABI
position lookup and does not by itself prove that no real exchange position
exists.

## 5. `CurrentTradeCycle` target shape

The current trade-cycle aggregate represents one complete entry-to-close lifecycle:

```text
CurrentTradeCycle
├── trade_cycle_id
├── phase
├── applied_entry_package: AppliedEntryPackage
│   ├── applied_desired_entry: DesiredEntry
│   └── calculated_quantity
├── frozen_entry_context: FrozenExecutedEntryContext | null
├── filled_quantity
├── remaining_quantity
├── average_entry_price | null
├── first_fill_at_ms | null
├── last_fill_at_ms | null
└── position_management_recipe | null
```

`CurrentTradeCycle` is the single Runtime aggregate for one sequential trading
cycle. This master plan details only its live-entry slice. The future open-trade
management model will be added inside the same aggregate as a separate design
slice.

The first implementation may introduce these fields incrementally, but the ownership boundary should remain stable.

## 6. Runtime and execution identities

The relevant identities have separate purposes:

```text
strategy_instance_id
= which deployed strategy owns the execution

trade_cycle_id
= which Runtime trade lifecycle and its single current entry package this execution belongs to
```

In Live V1, one `CurrentTradeCycle` owns at most one current entry package.
Therefore, `strategy_instance_id + trade_cycle_id` is the complete Runtime
ownership and callback binding pair.

A separate Runtime-owned `command_id` remains a future gate and may be introduced
only if a later command-idempotency design proves that an independently durable
command identity is required.

Exchange orders and fills may have their own ABI/exchange identifiers inside ABI's execution ledger.

## 7. `CurrentTradeCycle` phases

The first implementation uses only:

```text
awaiting_entry
partially_filled
position_open
```

Meanings:

- `awaiting_entry`: ABI acknowledged the entry package; no fill exists yet.
- `partially_filled`: at least one fill exists and some entry quantity remains.
- `position_open`: the entry is fully filled or ABI reports that entry execution is complete with a real open quantity.

A generic `closing` phase is **not implemented now**. It may be reconsidered later for a future limit-exit workflow where a closing order remains pending while the position still exists. Market exits and ordinary active stop/take protection do not require a `closing` state.

## 8. Singular desired-entry semantics

A live-entry calculation produces exactly:

```text
desired_entry: DesiredEntry | null
```

`DesiredEntry` contains:

```text
DesiredEntry
├── side: long | short
├── source_plan_bar_open_time_ms
├── planned_entry_price
├── initial_stop_price
├── initial_take_price
└── locked_exit_profile
```

Engine chooses the side. Runtime performs no side arbitration and defines no
separate long/short desired or execution objects.

## 9. ABI quantity boundary

Runtime does not calculate exchange quantity or own ABI bankroll, account-risk,
or leverage policy.

ABI owns quantity calculation using its own:

- bankroll and account state;
- risk policy;
- standard unit definition;
- leverage policy;
- symbol quantity steps and minimums;
- current capital allocation.

No binary floating-point conversion is allowed across this boundary.

## 10. Meaning of the Engine projection result

`LiveEntryProjectedStrategyInstance` expresses desired strategy state only.

It does not prove that:

- an exchange order exists;
- ABI accepted the package;
- a stop or take exists;
- any quantity has filled;
- Runtime may mark a position as open.

The Engine projection becomes repository execution state only after successful
ABI reconciliation.

## 11. `EntryReconciliationOrchestrator`

The reconciliation orchestrator is implemented as a nested application
component. Its operation receives only:

```text
LiveEntryProjectedStrategyInstance
```

The first operation step extracts the exact source aggregate from the embedded
projection provenance:

```text
source_state =
    projection.source.resolved_state.runtime_state
```

It accepts no separate state argument and does not reload or derive a second
snapshot. It compares the new `desired_entry` with the currently applied
`desired_entry` stored in `source_state.current_trade_cycle`:

```text
new desired_entry
vs
currently applied desired_entry
→ NO_OP / APPLY / REPLACE / CANCEL
```

Its responsibility is to decide what must change, reserve an apply-only cycle
identity when required, execute the command through its narrow application
execution port, accept only an existing successful-confirmation variant, and
return the unchanged or replacement aggregate to its caller. Concrete ABI
request construction, response adaptation, and production wiring remain
outside this component.

It does not:

- acquire or release the keyed mutex;
- reload repository state;
- save repository state;
- accept a second state snapshot supplied by the caller.

It does not contain exchange-specific create/amend/cancel sequences.

## 12. Reconciliation decisions

The internal comparison produces one of four decisions:

```text
NO_OP
APPLY
REPLACE
CANCEL
```

Semantics:

- `NO_OP`: desired and applied singular entries are already equivalent, or both are absent.
- `APPLY`: no acknowledged entry package exists and a `DesiredEntry` now exists.
- `REPLACE`: an acknowledged unfilled package exists and the `DesiredEntry` changed.
- `CANCEL`: an acknowledged unfilled package exists and `desired_entry` became null.

These are internal Runtime decisions, not long-lived trade phases and not necessarily separate ABI endpoints.

## 13. Desired-state ABI command

Pure reconciliation produces one transport-free business command:

```text
EntryReconciliationCommand
├── strategy_instance_id
├── trade_cycle_id
├── ticker
└── desired_entry: DesiredEntry | null
```

`desired_entry = DesiredEntry` means create or replace the desired package.
`desired_entry = null` means no pending entry package should remain for the
trade cycle.

An existing `DesiredEntry` always contains a positive exact-decimal
`initial_take_price`. Missing or null take is malformed Engine output, not an
alternative entry mode. Runtime must fail closed before forming an `APPLY` or
`REPLACE` command, so reconciliation never sends ABI an entry package without
take.

ABI decides whether the exchange implementation requires create, amend, cancel-and-recreate, or another sequence.

All ABI calls have a bounded timeout. An ambiguous create/replace result is
surfaced as an ordinary failure; Live V1 adds no special state or recovery flow,
and later committed-bar cycles continue through the ordinary pipeline. This
accepted limitation may be revisited after initial operational testing.

## 14. Atomic attached entry package

For the first implementation, one desired entry package represents:

```text
entry order
+ attached stop
+ attached take
```

Runtime reconciliation treats the Engine-derived entry, stop, take, and side as
one semantic desired-entry unit.

The package is indivisible: entry without initial take is architecturally
invalid in the first version.

ABI owns:

- exchange order types and flags;
- quantity calculation;
- decimal/step normalisation;
- attached-order mechanics;
- rollback or fail-closed behaviour if the package cannot be established consistently.

Runtime must not consider the command successful if only part of the package was applied.

## 15. ABI acknowledgement contract

A successful ABI reply means:

> the desired attached entry package for this trade cycle was processed and is now the acknowledged ABI state.

The existing wire success DTO contains:

```text
strategy_instance_id
trade_cycle_id
status = entry_package_applied
applied_desired_entry: DesiredEntry
calculated_quantity
```

A later concrete ABI adapter validates the wire result and adapts it to the
existing pure confirmation boundary:

```text
EntryAppliedConfirmation
├── strategy_instance_id
├── trade_cycle_id
├── applied_desired_entry
└── calculated_quantity
```

`AppliedEntryPackage` contains only `applied_desired_entry +
calculated_quantity`. Exchange order references, attached-order references, and
execution phase are not part of this acknowledgement or the minimal applied
package.

The implemented `EntryReconciliationOrchestrator` receives that confirmation
through its transport-free application execution port and rejects values
outside the closed successful-confirmation union before invoking the pure
applier.

## 16. Creation and update of `CurrentTradeCycle`

Runtime creates the first `CurrentTradeCycle` only after ABI successfully acknowledges the package.

For first apply:

```text
current_trade_cycle = CurrentTradeCycle(
    phase = awaiting_entry,
    applied_entry_package = AppliedEntryPackage(
        applied_desired_entry = acknowledged desired_entry,
        calculated_quantity = acknowledged calculated quantity,
    ),
    frozen_entry_context = null,
    ...
)
```

For replace, Runtime updates the existing `awaiting_entry` execution only after the replacement acknowledgement succeeds.

If ABI fails or rejects the desired change:

- the new Engine `DesiredEntry` does not become the applied desired entry;
- an existing applied `DesiredEntry` remains authoritative;
- if no package had ever been acknowledged, no `awaiting_entry` execution is created.

## 17. Mutable desired entry and frozen executed context

Before the first fill:

```text
CurrentTradeCycle.applied_entry_package.applied_desired_entry: DesiredEntry
```

is mutable through successful reconciliation.

After the first partial or full fill:

```text
FrozenExecutedEntryContext
├── desired_entry: DesiredEntry
├── entry_bar_open_time_ms
└── executed_entry_price
```

The context is frozen because real market exposure now exists. It references
the one applied `DesiredEntry`, whose `side` is authoritative. Later live-entry
projections may not replace the entry semantics of the active trade cycle.

The future open-trade receipt is constructed from this same singular context:

```text
OpenTradeReceipt
├── desired_entry: DesiredEntry
└── entry_bar_open_time_ms
```

Receipt construction must not introduce long/short receipt branches or
duplicate execution objects. `executed_entry_price` remains a Runtime/ABI
execution fact and is not transmitted to Strategy Engine.

## 18. Replace and cancel before fill

While phase is `awaiting_entry`:

- a changed `DesiredEntry` may produce `REPLACE`;
- a null `desired_entry` may produce `CANCEL`;
- an unchanged `DesiredEntry` produces `NO_OP`.

For Live V1, a successful ABI `entry_package_absent` response is the
authoritative confirmation of cancellation. Runtime then completes the current
entry lifecycle and clears `current_trade_cycle`.

If ABI returns an error or the cancel request times out, Runtime preserves the
existing `current_trade_cycle`, records the error, and introduces no new
state. More complex cancellation edge cases, cancel/fill races, and late
execution callbacks are deferred until there is concrete operational need.

After the first fill, live-entry replacement/cancellation no longer controls the trade cycle. The position-management branch becomes responsible for future decisions.

## 19. ABI execution webhook

ABI sends a separate webhook for every partial or complete entry fill.

A fill event conceptually contains:

```text
event_id
fill_id
strategy_instance_id
trade_cycle_id
exchange order reference
fill_quantity
fill_price
cumulative_filled_quantity
remaining_quantity
average_entry_price
occurred_at_ms
```

ABI must bind exchange orders to the Runtime ownership identities before emitting the callback.
The event model does not carry or reconstruct side-wise entry objects. After
identity validation, each fill applies to the one
`CurrentTradeCycle.applied_entry_package.applied_desired_entry`; the first fill
freezes that same object inside `FrozenExecutedEntryContext`.

## 20. `AbiExecutionEventOrchestrator`

The webhook path performs:

```text
1. Parse and validate the event.
2. Acquire the local keyed mutex for strategy_instance_id.
3. Load the current StrategyInstanceRuntimeState after acquiring the mutex.
4. Require a matching CurrentTradeCycle.
5. Validate strategy_instance_id and trade_cycle_id.
6. Apply the fill aggregate.
7. Freeze the singular executed entry context on the first fill.
8. Advance the execution phase.
9. Save the complete aggregate and release the mutex.
```

HTTP handlers never mutate `CurrentTradeCycle` directly.
The mutex is the same mutex used by closed-bar reconciliation, so a webhook may
wait for an in-flight ABI call but never applies a state snapshot captured
before waiting. Durable duplicate-fill suppression is not part of Live V1.

## 21. Partial-fill state transitions

First partial fill:

```text
awaiting_entry
-> partially_filled
```

Immediate full fill:

```text
awaiting_entry
-> position_open
```

Later partial fills:

```text
partially_filled
-> partially_filled
```

Final fill:

```text
partially_filled
-> position_open
```

The first partial fill already creates real market exposure and must be treated as an open position for subsequent Engine routing.

## 22. Fill storage and average price

Runtime does not implement a detailed duplicate fill ledger in the first version.

ABI remains authoritative for full exchange-order and fill history. Runtime
stores only the minimum Live V1 state needed for routing and Engine requests:

```text
filled_quantity
remaining_quantity
average_entry_price
first_fill_at_ms
last_fill_at_ms
```

The preferred first-version contract is that ABI sends the current cumulative `average_entry_price`, based on exchange data where available or calculated inside ABI from its authoritative fill ledger. Runtime accepts and persists that aggregate instead of retaining every detailed fill object and independently rebuilding the average.

Before implementation, the ABI/Bybit review must confirm exactly which cumulative fill and average-price fields the exchange supplies and which values ABI must calculate.

## 23. Routing after the first fill

`CurrentTradeCycle.phase` is a Runtime lifecycle invariant, not proof of the
current exchange position. On every committed-bar cycle, the existing ABI
open-position resolver obtains the authoritative current `position_open` fact,
and the existing use-case router selects the Engine live-entry or open-trade
path from that fact. An ABI-reported open position without complete frozen
Runtime context fails closed.

## 24. Multi-strategy ownership on one ticker

ABI must preserve ownership per strategy instance and trade cycle even when the exchange aggregates positions for the same ticker and side.

Conceptually:

```text
exchange BTCUSDT long total
=
instance A owned quantity
+
instance B owned quantity
+ ...
```

Runtime never infers ownership from ticker, side, price, or total exchange position. ABI callbacks and lookups must carry explicit Runtime binding identities.

The detailed ABI virtual-position ledger remains subject to the later ABI data-model review.

## 25. Live V1 local serialization and deferred reliability

Live V1 intentionally runs as one Runtime process with one worker. Multiple
replicas and horizontal scaling are prohibited. One local non-reentrant keyed
mutex per `strategy_instance_id` is shared by the two top-level writer paths.
Different instances may be processed in parallel.

The closed-bar critical section is:

```text
acquire keyed mutex(strategy_instance_id)
→ get_or_create/load current aggregate
→ ABI open-position lookup
→ Strategy Engine projection
→ typed projection branch
→ live-entry reconciliation when applicable
→ save when state changed
→ release mutex
```

The ABI webhook critical section is:

```text
acquire the same keyed mutex(strategy_instance_id)
→ load fresh current aggregate
→ validate event binding
→ apply execution event
→ save
→ release mutex
```

The nested `EntryReconciliationOrchestrator` must not reacquire the same
non-reentrant mutex. The owner releases it on every success, rejection, timeout,
unsupported branch, and exception path.

Live V1 uses the existing in-memory
`StrategyInstanceRuntimeStateRepository`. SQLite or another durable persistence
adapter is a future gate and is not required for the initial launch.

This deliberately permits a fill webhook to wait behind position lookup,
Engine projection, or an ABI entry-package call. After it acquires the mutex,
it loads fresh repository state rather than applying a snapshot captured before
waiting.

Every outbound call made while holding the mutex must have a bounded timeout.
The ABI entry-package acknowledgement must not synchronously depend on Runtime
processing a webhook emitted by that same call; such a dependency would
deadlock the two requests on the shared mutex.

Live V1 adds no projection generations, post-lock reprojection, quarantine,
fail-stop mode, `outcome_unknown`, persisted pending actions, ABI lookup
recovery, or command idempotency. The existing mutex and ordinary lifecycle
invariants are the complete V1 guard. The residual risk is accepted for the
initial launch and may be revisited after operational testing.

The following mechanisms are explicitly deferred:

- repository revisions and compare-and-swap;
- persisted pending execution actions written before external calls;
- ABI command idempotency;
- idempotent application and durable deduplication of fill events;
- restart recovery and stale-response recovery;
- multi-worker and multi-replica deployment;
- distributed locking or another cross-process coordination mechanism.

They become required before horizontal scaling or stronger production
guarantees. This single-process local-mutex model is a conscious first-live
constraint, not the final production-scale solution. The architecture preserves
the extension point by routing mutations through repositories and dedicated
orchestrators rather than direct HTTP-handler mutation.

## 26. Responsibility layout, implementation sequence, and deferred topics

The accepted implementation direction is responsibility-based rather than a
speculative file tree:

- the nested `EntryReconciliationOrchestrator` application component is
  implemented and archived without mutex, repository-load, or repository-save
  ownership;
- the next change extends the existing `StrategyRuntimeOrchestrator` in place as
  the top-level closed-bar workflow and keyed-mutex owner;
- `AbiExecutionEventOrchestrator` remains a later independent ABI-webhook
  workflow and owner of that path's keyed critical section;
- no open-trade application component is introduced until that branch is
  separately designed.

Implementation sequence:

```text
EntryReconciliationOrchestrator                    DONE
Closed-bar StrategyRuntimeOrchestrator extension   NEXT
ABI execution-event workflow                       LATER
Entry/fill cross-flow                              LATER
Open-trade requirements and implementation         DEFERRED
```

The closed-bar extension calls the already implemented nested operation. It
does not create a new top-level orchestrator or reimplement reconciliation.
Production adapter and composition scope remains a subsequent integration seam
until the actual existing service interfaces have been inspected.

Deferred topics include:

- open-trade/position-management reconciliation;
- stop/take replacement after entry;
- market-close and close acknowledgements;
- a future pending limit-exit phase (`closing` or a more precise name);
- partial-entry remainder policy and timeouts;
- missed-callback/restart reconciliation and persisted pending actions;
- full ABI virtual-position ledger design;
- repository CAS, ABI command idempotency, fill-event idempotency, and
  multi-process concurrency control;
- exact production HTTP endpoint names and exchange-specific payloads.
