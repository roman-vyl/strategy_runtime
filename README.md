# Strategy Runtime

Strategy Runtime is the live orchestration service that sits between MDS
(market-data / closed-bar signals), Strategy Engine (pure strategy logic),
and ABI (the exchange execution service). On every closed bar it decides,
per strategy instance, whether to open a new position or manage an
already-open one, and drives that decision through ABI with verified
confirmations before ever touching its own state.

This document is the map for a first-time reader: what calls what, in what
order, and which module owns which decision.

## Architecture at a glance

```text
MDS
 │
 │ POST /v1/webhooks/closed-bar
 ▼
FastAPI closed_bar_webhook
 │
 │ CommittedBarEvent
 ▼
CommittedBarIntakeBoundary
 │
 ▼
CommittedBarIntakeWorker
 │
 ▼
┌──────────────────────────────┐
│ CommittedBarOrchestrator     │   [ORCHESTRATOR #1 — utility fan-out]
│                              │
│ catalog → selector → fan-out │
└──────────────┬───────────────┘
               │
               │ StrategyBarProcessingUnit
               ▼
      StrategyCycleHandoffBoundary
               │
               ▼
┌────────────────────────────────┐
│ StrategyRuntimeOrchestrator    │   [ORCHESTRATOR #2 — one strategy cycle]
│                                │
│ state → ABI position → router  │
└──────────────┬─────────────────┘
               │
               ▼
        StrategyUseCaseRouter
          /             \
         /               \
 position_open=false    position_open=true
       │                     │
       ▼                     ▼
 Live Entry Engine       Open Trade Engine
 Projection              Projection
       │                     │
       ▼                     ▼
 LiveEntryProjected      OpenTradeProjected
 StrategyInstance        StrategyInstance
       │                     │
       ▼                     ▼
┌───────────────────┐   ┌───────────────────────┐
│ EntryReconciliation│  │ PositionManagement    │
│ Orchestrator       │  │ Orchestrator          │
│ [ORCHESTRATOR #3]  │  │ [ORCHESTRATOR #4]     │
└────────┬───────────┘   └──────────┬────────────┘
         │                          │
         ▼                          ▼
 ABI Entry Package          ABI Protection / Close
         │                          │
         ▼                          ▼
   resulting state             resulting state
         │                          │
         └────────────┬─────────────┘
                      ▼
             outer Runtime save
              (save only if state changed)
```

A fifth orchestrator lives outside this bar-driven pipeline entirely: ABI
calls Runtime back on `PUT .../first-fill`, and that inbound event is
handled by `AbiExecutionEventOrchestrator` — see
[Orchestrators in this repository](#orchestrators-in-this-repository).

## Request lifecycle, step by step

### 1. Ingress: the MDS webhook

MDS posts `{instrument, timeframe, open_time_ms}` to
`POST /v1/webhooks/closed-bar`. FastAPI does no strategy logic here — it
builds a `CommittedBarEvent` and hands it to `CommittedBarIntakeBoundary`, a
bounded queue. The HTTP request is acknowledged as soon as the event is
accepted into the queue, not once processing finishes.

Exactly one `CommittedBarIntakeWorker` drains that queue, FIFO, single
consumer, and calls `CommittedBarOrchestrator.process(event)`. The worker
itself is a concurrency primitive, not a business orchestrator.

### 2. `CommittedBarOrchestrator` — utility fan-out

The first real orchestrator, and deliberately the dumbest one. It knows
nothing about Engine, ABI, positions, or trade cycles. Its only question is:

> *Which strategy instances does this closed bar concern?*

It loads a deployment-catalog snapshot, asks the deployment selector for
every enabled deployment matching the bar's instrument and base timeframe,
and builds one `StrategyBarProcessingUnit` per match. Units are dispatched
one at a time, in `strategy_instance_id` order, into
`StrategyCycleHandoffBoundary` — a pass-through seam with no decision logic
of its own, wired in production to call
`StrategyRuntimeOrchestrator.process(unit)`.

### 3. `StrategyRuntimeOrchestrator` — one strategy cycle

This is where strategy state actually enters the picture. For a single
`StrategyBarProcessingUnit`, the orchestrator:

1. Acquires a keyed mutex on `strategy_instance_id` — the entire cycle below
   runs under that lock, serializing every writer (including the first-fill
   callback) for that one strategy instance.
2. Loads or creates the `StrategyInstanceRuntimeState` via
   `state_repository.get_or_create(...)`.
3. Asks `OpenPositionResolver.resolve(state)` whether ABI currently
   considers this trade cycle's position open.
4. Routes the result through `StrategyUseCaseRouter`.
5. Executes whichever branch the router selected, and persists the result
   only if it actually changed.

### 4. `OpenPositionResolver` — which of the two paths applies

The resolver answers exactly one question: *is there an open position for
the current trade cycle?* It does not route and does not decide what to do
about the answer.

- If `current_trade_cycle` is `null`, the answer is `position_open = false`
  and ABI is never called — there is nothing yet to ask about.
- If a `current_trade_cycle` exists, Runtime calls
  `GET /v1/strategy-instances/{sid}/trade-cycles/{tcid}/open-position` and
  gets back `position_open`, `first_fill_at_ms`, and `average_entry_price`.

The result is packaged as `PositionResolvedStrategyInstanceRuntimeState`.

### 5. First-fill freeze (open-position branch only)

Before routing, if ABI reports `position_open = true`,
`StrategyRuntimeOrchestrator` calls the existing `apply_first_fill(...)`
using `current_trade_cycle` and ABI's `first_fill_at_ms`, producing an
immutable frozen entry context. On the first observation this is saved
immediately; on every later cycle it is a no-op. The open-trade projection
below depends on this frozen context existing.

### 6. `StrategyUseCaseRouter` — the one real fork

The router receives a fully assembled
`PositionResolvedStrategyInstance` (processing unit + resolved state) and
makes exactly one decision:

```text
position_open ?
  false → Live Entry projection
  true  → Open Trade projection
```

It does not decide *what* the strategy should do — only which Engine
endpoint the cycle needs.

### 7a. No position → Live Entry projection

The router builds a `LiveEntryProjectionRequest` (`strategy_id`,
`raw_spec`, `ticker`, `base_timeframe`, `target_bar_open_time_ms`) and calls
Strategy Engine's live-entry endpoint, which returns `desired_entry:
DesiredEntry | null`. The router wraps this as
`LiveEntryProjectedStrategyInstance` and hands it back — it performs no
reconciliation itself.

`StrategyRuntimeOrchestrator` then calls
`EntryReconciliationOrchestrator.execute(projection)` — **orchestrator
#3**. It compares Engine's `desired_entry` against
`current_trade_cycle` and produces a pure decision: `NoOp`, `Apply`,
`Replace`, or `Cancel` (a new `Apply` mints a new `trade_cycle_id`). A
non-`NoOp` decision becomes an `EntryReconciliationCommand`, sent through
`AbiEntryPackageExecutionBridge` → `HttpxAbiEntryPackageAdapter` →
`PUT .../entry-package`. Only once ABI's confirmation is verified does the
bridge apply it to the aggregate and return the resulting
`StrategyInstanceRuntimeState`.

### 7b. Open position → Open Trade projection

The router instead builds an `OpenTradeProjectionRequest` from the
*frozen* entry context (`registered_spec_snapshot`,
`frozen_entry_context.desired_entry`,
`frozen_entry_context.entry_bar_open_time_ms`) plus the current bar's
`target_bar_open_time_ms`, and calls Strategy Engine's open-trade endpoint.
Engine returns `desired_protection`, `close_signal`, and `diagnostics`,
which Runtime turns into a `PositionManagementRecipe`. The router wraps this
as `OpenTradeProjectedStrategyInstance`.

`StrategyRuntimeOrchestrator` then calls
`PositionManagementOrchestrator.execute(projection)` — **orchestrator #4**,
the mirror image of #3:

```text
PositionManagementRecipe
        │
        ▼
decide_position_management
        │
   ┌────┼─────────────┐
   ▼    ▼             ▼
 NoOp  ApplyProtection ClosePosition
        │                │
        ▼                ▼
 ApplyProtectionCommand  ClosePositionCommand
        │                │
        ▼                ▼
 PositionManagementExecutionPort
        │                │
        ▼                ▼
 verified            verified
 ProtectionApplied   PositionClosed
 Confirmation        Confirmation
        │                │
        ▼                ▼
   new Runtime state (or unchanged on NoOp)
```

`PositionManagementExecutionPort` is implemented over HTTP by
`HttpxAbiPositionManagementAdapter`: `ApplyProtection` → `PUT
.../protection`, `ClosePosition` → bodyless `DELETE .../open-position`. Both
calls return a confirmation only when ABI's response exactly matches the
sent command; anything else fails closed as a typed error, never a silent
retry.

### 8. Persistence — one rule, applied once

Both branches converge on the same rule inside
`StrategyRuntimeOrchestrator`: compare the branch's resulting state against
the state the cycle started with. If unchanged, return it as-is — no write.
If changed, `state_repository.save(resulting_state)` and return the saved
state. There is exactly one save decision per cycle, made in the outer
orchestrator, never inside either branch orchestrator.

## Orchestrators in this repository

Five components carry the name `...Orchestrator`. Three of them sit on the
closed-bar path described above; the other two sit outside it.

| Component | Role | On the closed-bar path? |
|---|---|---|
| `CommittedBarOrchestrator` | bar → matching deployments → fan-out | Yes |
| `StrategyRuntimeOrchestrator` | one strategy cycle, start to persisted finish | Yes |
| `EntryReconciliationOrchestrator` | live-entry decision → ABI confirmation → state | Yes — no-position branch |
| `PositionManagementOrchestrator` | management decision → ABI confirmation → state | Yes — open-position branch |
| `AbiExecutionEventOrchestrator` | inbound ABI first-fill callback → state | No — separate inbound HTTP path, sharing the same repository and keyed-mutex registry |

`EntryReconciliationOrchestrator` and `PositionManagementOrchestrator` are
siblings behind one router, not a chain: `StrategyRuntimeOrchestrator` calls
exactly one of them per cycle, and persistence stays owned by the outer
orchestrator in both cases.

`AbiExecutionEventOrchestrator` reuses the same
`StrategyInstanceRuntimeStateRepository` and
`StrategyInstanceKeyedMutexRegistry` as `StrategyRuntimeOrchestrator`, so a
first-fill callback and a closed-bar cycle for the same strategy instance
are always serialized against each other, never racing.

## HTTP surface

```text
GET  /health/live
GET  /health/ready
POST /v1/webhooks/closed-bar
PUT  /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill
```

Example webhook call:

```bash
curl -X POST http://127.0.0.1:8093/v1/webhooks/closed-bar \
  -H 'content-type: application/json' \
  -d '{"instrument":"BTCUSDT.P","timeframe":"5m","open_time_ms":1784106300000}'
```

The webhook acknowledges accepted work before background orchestration
completes; the first-fill endpoint is ABI's callback into the shared
repository/mutex pair described above.

## Local setup

```bash
make install-dev
make verify
make run
```

`make install-dev` creates a repository-local `.venv` with Python 3.12. All
other Make targets require that exact environment and never fall back to a
system `python` or `python3`.

Default configuration is documented in `config/runtime.env.example`.

## Further reading

Deeper, more granular planning and contract documents live under
[`docs/system-plans/`](docs/system-plans/README.md), and the authoritative,
per-capability contracts live under
[`openspec/specs/`](openspec/specs) with historical change proposals under
[`openspec/changes/archive/`](openspec/changes/archive). This README is the
map; those are the territory.
