# Runtime ↔ ABI entry reconciliation master plan

Status: discussion-approved high-level plan for the second half of the Runtime live-entry pipeline. This document is not an OpenSpec change and does not yet authorize implementation.

The plan starts at the point where Runtime already owns one typed Strategy Engine projection result and ends at the point where ABI execution events have updated the durable strategy-instance state.

## 1. Scope and starting boundary

The first half of the closed-bar pipeline ends with one of two typed objects:

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
-> CurrentTradeExecution
-> ABI partial/full fill webhooks
-> Runtime state transition
```

The open-trade/position-management reconciliation branch will be designed separately after this entry branch is settled.

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

## 3. Orchestrator structure

The synchronous closed-bar path is coordinated by one top-level strategy-cycle orchestrator containing autonomous phases:

```text
StrategyBarCycleOrchestrator
├── ProjectionOrchestrator
└── EntryReconciliationOrchestrator
```

The projection object is passed directly from the first phase to the second as a typed in-memory object. Engine responses are not written to an intermediate temporary store merely to continue the same request.

Realtime ABI callbacks are handled by a separate orchestrator:

```text
AbiExecutionEventOrchestrator
```

Both orchestrator paths meet only through the durable `StrategyInstanceRuntimeStateRepository`.

## 4. Strategy-instance aggregate

`CurrentTradeExecution` is nested inside the long-lived strategy-instance aggregate:

```text
StrategyInstanceRuntimeState
├── strategy_instance_id
├── registered_deployment
└── current_trade_execution: CurrentTradeExecution | null
```

`registered_deployment` is the immutable Runtime deployment snapshot containing:

```text
strategy_id
ticker
base_timeframe
raw_spec
derived strategy_instance_id
```

`current_trade_execution = null` means that the instance currently owns no acknowledged entry package and no real open position.

## 5. `CurrentTradeExecution` target shape

The active trade execution object represents one complete entry-to-close lifecycle:

```text
CurrentTradeExecution
├── trade_cycle_id
├── execution_intent_id
├── phase
├── active_entry_recipe
├── frozen_entry_recipe | null
├── applied_entry_package
├── processed_fill_ids
├── filled_quantity
├── remaining_quantity
├── average_entry_price | null
├── first_fill_at_ms | null
├── last_fill_at_ms | null
└── position_management_recipe | null
```

The first implementation may introduce these fields incrementally, but the ownership boundary should remain stable.

## 6. Runtime and execution identities

The relevant identities have separate purposes:

```text
strategy_instance_id
= which deployed strategy owns the execution

trade_cycle_id
= which Runtime trade lifecycle this execution belongs to

execution_intent_id
= which concrete ABI entry intention is being reconciled
```

`execution_intent_id` is not an exchange-order ID and not a fill ID. Its purpose is to give one stable identity to the desired entry package so ABI can safely recognise retries, replacements, cancellations, acknowledgements, and later fill callbacks as belonging to the same entry intention instead of creating duplicate packages.

Exchange orders and fills may have their own ABI/exchange identifiers inside ABI's execution ledger.

## 7. `CurrentTradeExecution` phases

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

## 8. Live-entry recipe semantics

A live-entry calculation produces an entry recipe containing a desired plan or no plan.

The current Engine model may still expose long and short slots. Runtime does not add a separate prohibition merely for both being non-null; simultaneous long and short plans are not expected under the accepted trading logic.

The effective desired plan contains:

```text
side
planned_entry_price
initial_stop_price
initial_take_price
risk_multiplier
locked_exit_profile
source_plan_bar_open_time_ms
```

## 9. Risk sizing boundary

Runtime does not calculate an exchange quantity and does not own bankroll/risk configuration.

The Engine/live-entry result supplies:

```text
risk_multiplier
```

`risk_multiplier` is an exact decimal value expressed in relative units. Examples such as `0.1`, `1`, `2`, or `3` mean fractions or multiples of one ABI-defined standard position/risk unit.

ABI owns the interpretation of this multiplier using its own:

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

The Engine projection becomes durable execution state only after successful ABI reconciliation.

## 11. `EntryReconciliationOrchestrator`

The reconciliation orchestrator receives:

```text
LiveEntryProjectedStrategyInstance
+
StrategyInstanceRuntimeState
```

It compares the newly desired recipe with the currently ABI-applied recipe stored in `CurrentTradeExecution`.

Its responsibility is to decide what must change, call the ABI entry-package port when necessary, validate the acknowledgement, and persist the resulting Runtime aggregate.

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

- `NO_OP`: desired recipe and applied recipe are already equivalent, or both are absent.
- `APPLY`: no acknowledged entry package exists and a desired recipe now exists.
- `REPLACE`: an acknowledged unfilled package exists and the desired recipe changed.
- `CANCEL`: an acknowledged unfilled package exists and the new desired recipe disappeared.

These are internal Runtime decisions, not long-lived trade phases and not necessarily separate ABI endpoints.

## 13. Desired-state ABI command

Runtime sends one business command representing the desired entry package, conceptually:

```text
ReconcileDesiredEntryPackage
├── strategy_instance_id
├── trade_cycle_id
├── execution_intent_id
├── ticker
└── desired_entry: plan | null
```

`desired_entry = plan` means create or replace the desired package.

`desired_entry = null` means no pending entry package should remain for this intent.

ABI decides whether the exchange implementation requires create, amend, cancel-and-recreate, or another sequence.

## 14. Atomic attached entry package

For the first implementation, one desired entry package represents:

```text
entry order
+ attached stop
+ attached take
```

Runtime sends the desired entry, stop, take, side, and `risk_multiplier` as one semantic unit.

ABI owns:

- exchange order types and flags;
- quantity calculation;
- decimal/step normalisation;
- attached-order mechanics;
- rollback or fail-closed behaviour if the package cannot be established consistently.

Runtime must not consider the command successful if only part of the package was applied.

## 15. ABI acknowledgement contract

A successful ABI reply means:

> the desired attached entry package for this execution intent was processed and is now the acknowledged ABI state.

It must contain enough binding and execution information to persist Runtime state, including conceptually:

```text
strategy_instance_id
trade_cycle_id
execution_intent_id
status = entry_package_applied
accepted risk multiplier / calculated quantity summary
entry order reference
attached stop reference
attached take reference
current execution status = awaiting_entry
```

The exact exchange payload remains ABI-private unless Runtime needs a specific field for later correlation or diagnostics.

## 16. Creation and update of `CurrentTradeExecution`

Runtime creates the first `CurrentTradeExecution` only after ABI successfully acknowledges the package.

For first apply:

```text
current_trade_execution = CurrentTradeExecution(
    phase = awaiting_entry,
    active_entry_recipe = acknowledged recipe,
    frozen_entry_recipe = null,
    ...
)
```

For replace, Runtime updates the existing `awaiting_entry` execution only after the replacement acknowledgement succeeds.

If ABI fails or rejects the desired change:

- the new Engine recipe does not become the applied recipe;
- an existing applied recipe remains authoritative;
- if no package had ever been acknowledged, no `awaiting_entry` execution is created.

## 17. Mutable and frozen entry recipe

Before the first fill:

```text
active_entry_recipe
```

is mutable through successful reconciliation.

After the first partial or full fill:

```text
frozen_entry_recipe = active_entry_recipe
```

The recipe is frozen because real market exposure now exists. Later live-entry projections may not replace the entry semantics of the active trade cycle.

## 18. Replace and cancel before fill

While phase is `awaiting_entry`:

- a changed desired recipe may produce `REPLACE`;
- a disappeared desired recipe may produce `CANCEL`;
- an unchanged desired recipe produces `NO_OP`.

After the first fill, live-entry replacement/cancellation no longer controls the trade cycle. The position-management branch becomes responsible for future decisions.

## 19. ABI execution webhook

ABI sends a separate webhook for every partial or complete entry fill.

A fill event conceptually contains:

```text
event_id
fill_id
strategy_instance_id
trade_cycle_id
execution_intent_id
exchange order reference
fill_quantity
fill_price
cumulative_filled_quantity
remaining_quantity
average_entry_price
occurred_at_ms
```

ABI must bind exchange orders to the Runtime ownership identities before emitting the callback.

## 20. `AbiExecutionEventOrchestrator`

The webhook path performs:

```text
1. Parse and validate the event.
2. Load StrategyInstanceRuntimeState by strategy_instance_id.
3. Require a matching CurrentTradeExecution.
4. Validate trade_cycle_id and execution_intent_id.
5. Ignore an already processed fill_id.
6. Apply the fill aggregate.
7. Freeze the recipe on the first fill.
8. Advance the execution phase.
9. Save the complete aggregate.
```

HTTP handlers never mutate `CurrentTradeExecution` directly.

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

ABI remains authoritative for full exchange-order and fill history. Runtime stores only the minimum state needed for routing, idempotency, and Engine requests:

```text
processed_fill_ids
filled_quantity
remaining_quantity
average_entry_price
first_fill_at_ms
last_fill_at_ms
```

The preferred first-version contract is that ABI sends the current cumulative `average_entry_price`, based on exchange data where available or calculated inside ABI from its authoritative fill ledger. Runtime accepts and persists that aggregate instead of retaining every detailed fill object and independently rebuilding the average.

Before implementation, the ABI/Bybit review must confirm exactly which cumulative fill and average-price fields the exchange supplies and which values ABI must calculate.

## 23. Routing after the first fill

The next committed-bar route must use a semantic predicate such as:

```text
has_open_position
```

It is true for at least:

```text
partially_filled
position_open
```

Therefore, after the first fill, the next MDS cycle uses the Engine open-trade path rather than live-entry projection.

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

## 25. Minimal reliability now; concurrency later

The first version requires only basic idempotency:

- repeating reconciliation for the same `execution_intent_id` must not create duplicate packages;
- repeating a webhook with the same `fill_id` must not increase the Runtime position twice.

The first version deliberately does not yet implement:

- per-instance queues;
- distributed locks;
- optimistic revision/CAS protocols;
- transactional outbox;
- complex stale-response recovery.

The architecture keeps future insertion points by requiring all mutations to pass through repositories and dedicated orchestrators rather than direct HTTP-handler mutation.

## 26. Module structure, implementation sequence, and deferred topics

Proposed responsibility layout:

```text
src/strategy_runtime/runtime/
├── orchestrator/
│   ├── strategy_bar_cycle.py
│   ├── projection.py
│   ├── entry_reconciliation.py
│   └── abi_execution_event.py
├── state/
│   ├── strategy_instance.py
│   ├── current_trade_execution.py
│   └── repository.py
├── reconciliation/
│   ├── entry_diff.py
│   ├── entry_commands.py
│   └── entry_results.py
└── abi/
    ├── entry_package_port.py
    ├── entry_package_models.py
    └── execution_event_models.py
```

Planned implementation order after this document is approved:

1. Finalise the `CurrentTradeExecution` model and invariants.
2. Finalise `EntryRecipe`/`LiveEntryPlan` fields including exact decimal `risk_multiplier`.
3. Define reconciliation decisions and equivalence rules.
4. Define the ABI desired-entry-package port and acknowledgement models.
5. Define ABI fill-event models and minimal fill aggregate state.
6. Implement `EntryReconciliationOrchestrator`.
7. Implement `AbiExecutionEventOrchestrator`.
8. Connect both to the strategy-instance repository.
9. Add state-machine and end-to-end tests with fake ABI.
10. Only then create corresponding OpenSpec changes.

Deferred topics include:

- open-trade/position-management reconciliation;
- stop/take replacement after entry;
- market-close and close acknowledgements;
- a future pending limit-exit phase (`closing` or a more precise name);
- partial-entry remainder policy and timeouts;
- missed-callback/restart reconciliation;
- full ABI virtual-position ledger design;
- advanced concurrency control;
- exact production HTTP endpoint names and exchange-specific payloads.
