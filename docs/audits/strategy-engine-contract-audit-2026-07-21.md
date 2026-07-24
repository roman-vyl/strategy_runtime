> **Superseded identity note (2026-07-23):** historical references to `strategy_version` and `compatibility_profile` describe the pre-simplification contract. Both fields are now removed from Runtime; see `runtime-strategy-selector-fields-removal-decision-2026-07-23.md`.

# Strategy Runtime ↔ Strategy Engine Contract Audit

Date: 2026-07-21

## 1. Purpose and scope

This audit compares:

- the current Strategy Runtime utility-contour output;
- the current Strategy Engine Phase 6 HTTP contracts;
- the existing Runtime high-level contract documents.

It does **not** design the semantic Runtime orchestrator, ABI client, receipt store, lifecycle state machine, retry policy, or Engine HTTP adapter. Its only purpose is to establish the exact information boundary for the next small Runtime design step.

## 2. Sources treated as current evidence

Runtime code:

- `StrategyBarProcessingUnit`;
- `DeploymentSpecification`;
- `CommittedBarEvent`;
- `StrategyCycleHandoffBoundary` and `StrategyCycleDispatchPort`.

Runtime high-level documents:

- `docs/system-plans/runtime-master-plan.md`;
- `docs/system-plans/runtime-state-and-lifecycle-plan.md`;
- `docs/system-plans/runtime-contract-map.md`.

Engine Phase 6 code:

- `LiveEntryProjectionRequestModel` / `LiveEntryProjectionResponseModel`;
- `OpenTradeProjectionRequestModel` / `OpenTradeProjectionResponseModel`;
- `ExecutedTradeReceiptModel`;
- `EvaluateLiveEntryProjection`;
- `EvaluateOpenTradeProjection`;
- `validate_open_trade_request`;
- HTTP routes `/v1/strategy-evaluations/live-entry` and `/v1/strategy-evaluations/open-trade`.

The contract expectations used by this audit are also stated directly in the
sections below.

## 3. Current Runtime utility-contour output

The utility contour hands off exactly one immutable unit:

```text
StrategyBarProcessingUnit
├── stable_deployment_id
├── deployment: DeploymentSpecification
│   ├── stable_deployment_id
│   ├── instrument
│   ├── base_timeframe
│   ├── strategy_id
│   ├── strategy_version
│   ├── compatibility_profile
│   ├── raw_spec
│   └── source_path
├── committed_bar: CommittedBarEvent
│   ├── instrument
│   ├── timeframe
│   └── open_time_ms
└── processing_context
    └── flow_id
```

`FilesystemDeploymentCatalog` currently defines:

```text
stable_deployment_id == deployment document instance_id
```

Therefore the unit already contains the Engine `instance_id`, although Runtime currently exposes it under the utility-layer name `stable_deployment_id`.

## 4. Exact Engine live-entry request

Current Engine HTTP request:

```text
LiveEntryProjectionRequestModel
├── strategy
│   ├── strategy_id
│   ├── strategy_version
│   ├── instance_id
│   ├── raw_spec
│   └── compatibility_profile
├── market
│   ├── ticker
│   └── base_timeframe
└── target_bar_open_time_ms
```

Endpoint:

```text
POST /v1/strategy-evaluations/live-entry
```

### 4.1 Field mapping from the utility unit

| Engine request field | Runtime source | Status |
|---|---|---|
| `strategy.strategy_id` | `unit.deployment.strategy_id` | available |
| `strategy.strategy_version` | `unit.deployment.strategy_version` | available |
| `strategy.instance_id` | `unit.stable_deployment_id` | available |
| `strategy.raw_spec` | `unit.deployment.raw_spec` | available; immutable mapping must be converted to JSON object for transport |
| `strategy.compatibility_profile` | `unit.deployment.compatibility_profile` | available |
| `market.ticker` | `unit.deployment.instrument` | available |
| `market.base_timeframe` | `unit.deployment.base_timeframe` | available |
| `target_bar_open_time_ms` | `unit.committed_bar.open_time_ms` | available |

### 4.2 Live-entry conclusion

The utility contour already contains every business field required by the Engine live-entry request.

No extra MDS, Engine, or ABI API query is required merely to construct this request.

The future semantic Runtime layer will still need to decide **whether** live-entry is permitted. That routing decision is outside this audit and requires ABI/lifecycle semantics. But once live-entry is selected, request composition is a pure deterministic transformation of `StrategyBarProcessingUnit`.

### 4.3 Information that must not be added by Runtime

Runtime must not add:

- candles;
- indicators;
- warmup history;
- feature plans or FeatureFrames;
- `market_data_hash` in the request;
- `config_hash` in the request;
- pending order details in the Engine request.

Engine calculates the canonical strategy config hash from the strategy envelope and obtains market data plus `market_data_hash` through its own MDS integration.

## 5. Exact Engine live-entry response

Current response:

```text
LiveEntryProjectionResponseModel
├── contract_version
├── strategy_id
├── strategy_version
├── instance_id
├── source_config_hash
├── market
├── target_bar_open_time_ms
├── market_data_hash
└── plans_by_side
    ├── long: complete plan | null
    └── short: complete plan | null
```

Each non-null plan contains:

```text
side
source_plan_bar_open_time_ms
planned_entry_price
initial_stop_price
initial_take_price
locked_exit_profile
```

The response is not yet consumed by current Runtime code. Future Runtime behavior must treat each side as an atomic complete plan or `null`; it must not synthesize a plan from partial fields.

## 6. Exact Engine open-trade request

Current Engine HTTP request:

```text
OpenTradeProjectionRequestModel
├── strategy                 # same envelope as live-entry
├── market                   # ticker + base timeframe
├── target_bar_open_time_ms
└── executed_trade_receipt
```

Endpoint:

```text
POST /v1/strategy-evaluations/open-trade
```

The first three branches are fully derivable from `StrategyBarProcessingUnit`, exactly as in live-entry.

The fourth branch is not present in the utility output.

## 7. Executed-trade receipt required by Engine

The current Engine requires the complete immutable receipt:

```text
ExecutedTradeReceipt
├── trade_id
├── instance_id
├── strategy_id
├── strategy_version
├── source_config_hash
├── ticker
├── base_timeframe
├── side
├── source_plan_bar_open_time_ms
├── entry_bar_open_time_ms
├── planned_entry_price
├── executed_entry_price
├── initial_stop_price
├── initial_take_price
├── locked_exit_profile
└── abi_entry_correlation
```

### 7.1 Which receipt fields originate in the earlier live-entry response

- `instance_id`;
- `strategy_id`;
- `strategy_version`;
- `source_config_hash`;
- `ticker`;
- `base_timeframe`;
- `side`;
- `source_plan_bar_open_time_ms`;
- `planned_entry_price`;
- `initial_stop_price`;
- `initial_take_price`;
- `locked_exit_profile`.

### 7.2 Which receipt fields require execution facts

- `trade_id`;
- `entry_bar_open_time_ms`;
- `executed_entry_price`;
- `abi_entry_correlation`.

These cannot be invented by Runtime from the deployment or committed-bar event. They must come from the approved ABI fill/execution contract and then be frozen into Runtime-owned immutable receipt persistence.

## 8. Additional information required before choosing an Engine path

The Engine request contract alone does not tell Runtime which endpoint to call.

Existing accepted high-level semantics require Runtime to query ABI operational state for the correlated strategy instance before route selection.

Minimum semantic outcomes needed from ABI are:

```text
flat / closed
armed or pending entry
open position
closing / recovery / ambiguous
```

For the future small semantic orchestrator slice, the missing information is therefore not “more market data.” It is:

1. current ABI operational state for the instance;
2. sufficient correlation identity to bind that state to the deployment;
3. for an open position, the matching Runtime-persisted executed-trade receipt.

The exact ABI request/response DTO is not yet approved in this repository and must be designed separately before implementation.

## 9. Engine validation that Runtime must satisfy

Before Engine reads market data for `open-trade`, it validates:

- non-empty receipt identities;
- lowercase SHA-256 `source_config_hash`;
- side is `long` or `short`;
- supported locked exit profile;
- source-plan, entry, and target timestamps are timeframe-aligned;
- `source_plan <= entry <= target`;
- decimal prices are positive;
- stop/entry/take geometry matches side;
- request strategy identity matches receipt identity;
- request market identity matches receipt identity;
- Engine-calculated strategy config hash matches `source_config_hash`.

Therefore Runtime must pass the original pinned strategy envelope that produced the filled plan. It cannot safely combine a receipt from one deployment revision with the current contents of a changed deployment file.

This creates a future design requirement: receipt/open-trade processing must have access to the pinned strategy revision or must fail closed when the current deployment envelope no longer hashes to the receipt.

## 10. Exact Engine open-trade response

Current response:

```text
OpenTradeProjectionResponseModel
├── contract_version
├── trade_id
├── instance_id
├── strategy_id
├── strategy_version
├── source_config_hash
├── market
├── target_bar_open_time_ms
├── market_data_hash
├── desired_protection
│   ├── stop_price
│   └── take_price | null
├── close_signal
│   ├── active
│   ├── reason | null
│   ├── component_id | null
│   └── layer | null
└── diagnostics
    ├── phase
    ├── max_phase_reached
    ├── bars_in_trade
    ├── mfe_pct
    ├── mae_pct
    └── managed_events
```

Runtime must not reinterpret Engine close-signal priority or derive exchange fill facts from this result. The response expresses desired post-target strategy state, not what happened intrabar on the exchange.

## 11. Contract agreement between current documents and Engine code

The current high-level Runtime documents are materially aligned with Engine Phase 6 on these points:

- two separate endpoints exist: live-entry and open-trade;
- Runtime sends strategy envelope, market identity, and exact target bar;
- Runtime sends no candles or indicators;
- Engine owns MDS acquisition and feature calculation;
- open-trade additionally requires an immutable executed-trade receipt;
- ABI state, not receipt existence, proves whether the position is open;
- Engine returns `market_data_hash` and config provenance;
- Runtime must preserve, not calculate, returned provenance;
- Engine does not own exchange reconciliation.

## 12. Gaps and unresolved contract decisions

### 12.1 ABI operational-state API is not concrete

High-level states are described, but exact request fields, correlation keys, response schema, versioning, and failure semantics are not approved.

### 12.2 Receipt acquisition and persistence contract is not implemented

The Engine receipt schema is concrete, but Runtime has no current receipt model/store and no approved ABI fill DTO from which to create it.

### 12.3 Pinned strategy revision behavior needs an explicit Runtime decision

Engine validates receipt `source_config_hash` against the supplied strategy envelope. Runtime must define how it retrieves the exact pinned envelope after deployment files change.

### 12.4 Live-entry result persistence is not designed

Runtime needs a mutable pending-plan snapshot before fill, but its exact model, replacement policy, side selection, correlation, and lifecycle are not yet specified.

### 12.5 Utility identity naming differs from Engine naming

Runtime utility code uses `stable_deployment_id`; Engine uses `instance_id`. They currently have equal values by catalog construction. The semantic layer should map explicitly rather than introduce a second independent identity.

### 12.6 Transport behavior is not yet specified in Runtime

Timeouts, Engine error mapping, retry/idempotency, response validation, and provenance mismatch handling are deferred and must not be silently invented in the first semantic-orchestrator slice.

## 13. Boundary for the next small OpenSpec

The next small OpenSpec can safely cover only the following responsibility:

```text
StrategyBarProcessingUnit
    + abstract operational-state result
    + optional abstract matching receipt
    -> choose no Engine call, live-entry, or open-trade
    -> compose the selected typed Engine request
    -> hand that request to a typed Engine projection port
```

However, before writing that spec, the project must decide whether the first slice includes:

- only deterministic live-entry request composition; or
- route selection using an abstract ABI-state port; or
- both route selection and request composition.

This audit recommends the smallest non-speculative first slice:

```text
LiveEntryProjectionRequest composition from StrategyBarProcessingUnit
```

It requires no new external API contract and can be tested entirely against the current Engine request schema. Route selection and open-trade composition should follow only after the ABI operational-state and receipt boundaries are approved.

## 14. Final audit conclusion

The utility contour output is already sufficient to construct the exact current Engine `live-entry` request.

It is not sufficient to select the correct Engine path or to construct `open-trade`.

The missing inputs are:

```text
ABI operational state
+ correlation facts
+ matching immutable executed-trade receipt
+ access to the pinned strategy envelope/revision
```

No additional candles, indicators, feature state, or direct MDS payload are required from Runtime.
