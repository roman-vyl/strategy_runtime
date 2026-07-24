> **Superseded identity note (2026-07-23):** historical references to `strategy_version` and `compatibility_profile` describe the pre-simplification contract. Both fields are now removed from Runtime; see `runtime-strategy-selector-fields-removal-decision-2026-07-23.md`.

# Strategy Runtime Identifier Normalization and Refactoring Audit

Date: 2026-07-22
Status: working architectural audit; supersedes the identifier recommendations in `runtime-identifier-audit-2026-07-22.md`, but does not delete that historical file

## Purpose

This document inventories identifiers, hashes, temporal coordinates, API-version markers, and possible correlation keys used or proposed across:

- Strategy Runtime;
- Strategy Engine;
- ABI Executor Bot;
- Market Data Service;
- the Runtime utility pipeline.

For every value, the audit records:

- where it is born;
- how it is generated or obtained;
- what entity, fact, or calculation it identifies;
- which module owns its semantics;
- whether it crosses module or service boundaries;
- whether its current implementation must be preserved;
- the proposed refactoring, consolidation, removal, or deferral.

The primary goal is not to minimize the number of fields mechanically. The goal is to keep only identities that represent real durable entities, eliminate aliases that pretend to be separate identities, and avoid using IDs to correlate operations that are already structurally associated by synchronous object flow.

---

## 1. Governing architectural principles

### 1.1 Object enrichment replaces internal ID correlation

The Runtime pipeline passes complete typed objects through a deterministic call chain:

```text
StrategyBarProcessingUnit
→ StrategyInstanceRuntimeState
→ PositionResolvedStrategyInstance
→ EngineProjectedStrategyInstance
```

The same rule applies to synchronous HTTP calls:

```text
request object
→ synchronous HTTP call
→ response object
→ enrich the same source object
```

Therefore, no extra internal ID is needed merely to associate a synchronous response with its request or to find the source object again. The call stack and the containing typed object already provide that association.

IDs remain justified only when they identify a real durable entity, restore state after process loss, cross an asynchronous boundary, provide idempotency, or identify an external exchange fact.

### 1.2 Echo fields are validation, not correlation

When Engine returns fields that repeat request data, such as `strategy_instance_id`, market, or target bar, those fields are mandatory defensive echoes under the currently agreed contract.

Runtime compares them with the request and rejects a mismatch. They are not used to locate the original object and are not copied into a recipe as new state.

### 1.3 ABI Executor Bot has no backward-compatibility constraint

ABI Executor Bot was implemented before the current Runtime architecture stabilized. Its existing IDs, storage schema, request DTOs, response DTOs, journal format, and internal correlations are provisional.

They may be renamed, removed, merged, or replaced with breaking changes whenever the finalized Runtime-owned identity and lifecycle model requires it.

No dual-write, compatibility alias, migration bridge, or preservation of obsolete ABI contracts is required unless a later production constraint is explicitly introduced.

External exchange-generated identifiers remain factual exchange data, but ABI's representation and propagation of them are also refactorable.

---

## 2. Identifier and correlation inventory

| Identifier / value | Category and current status | Born in | Generation / source | Responsibility / purpose | Semantic owner | Cross-module or service exchange | Compatibility status | Refactoring proposal |
|---|---|---|---|---|---|---|---|---|
| `strategy_id` | Agreed business identity | Strategy definition / Engine registry | Stable symbolic name such as `ema_pullback` | Identifies the strategy family or algorithm | Strategy Engine / shared contract | Runtime → Engine | Canonical; preserve semantics | Keep. Prefer carrying it inside a `StrategyIdentity` or strategy envelope rather than as a loose method argument |
| `strategy_version` | Agreed version selector | Strategy implementation in Engine | Explicit implementation or strategy-contract version | Selects the version of strategy logic | Strategy Engine | Runtime → Engine; Engine → Runtime echo | Canonical while multiple strategy versions are possible | Keep as the strategy-implementation selector; carry inside the strategy envelope. It is not a transport-contract version |
| `stable_deployment_id` | Implemented utility-layer alias | Runtime deployment catalog | Stable value read or derived from deployment configuration | Identifies one deployed strategy instance during utility processing | Runtime utility layer | Internal utility handoff | Existing Runtime code may be refactored; no external compatibility requirement stated | Stop treating it as a second identity. Map it once to canonical `strategy_instance_id`; eventually rename the utility field if practical |
| `strategy_instance_id` | Agreed canonical durable identity | Runtime deployment catalog | Deterministically derived from immutable strategy semantics + ticker + base timeframe | Identifies one long-lived deployed strategy instance and keys its aggregate | Strategy Runtime | Runtime repository; Runtime → Engine; Runtime → ABI | Canonical target identity. ABI support is provisional and must adapt | Keep as the only canonical instance identity. Pass inside complete Runtime/HTTP objects; do not add separate correlation IDs for synchronous calls |
| `instance_id` | Implemented Engine transport alias | Runtime populates Engine DTO | Direct copy of `strategy_instance_id` | Names the same long-lived strategy instance in Engine API | Runtime semantics; Engine transport field | Runtime ↔ Engine | Engine contract is refactorable before stabilization | Rename to `strategy_instance_id` in Engine request/response DTOs. Until changed, treat strictly as an alias, never a separate stored ID |
| `trade_cycle_id` | Agreed conceptual durable identity | Strategy Runtime | Runtime-generated opaque ID, likely UUID/ULID | Identifies one entry → execution → management → close cycle inside a long-lived instance | Strategy Runtime | Runtime state; Runtime → Engine open-trade; future Runtime ↔ ABI async flows | New canonical target; exact creation point still open | Keep one Runtime-owned cycle identity. Carry it as part of `CurrentTradeCycle` / `FrozenEntryContext`, not as repeated loose arguments |
| `trade_id` | Implemented Engine contract alias with ambiguous name | Runtime currently supplies Engine field | Existing caller-provided field | Intended to identify one open-trade workflow | Historically Runtime-owned despite Engine field name | Runtime ↔ Engine | No backward compatibility required on Engine side for this project stage | Audit Engine usages, then replace with `trade_cycle_id`. Do not maintain two generated IDs or a permanent one-to-one mapping |
| `spec_revision_hash` | Utility-internal implementation detail only | Runtime utility catalog | Optional hash of canonical deployment content | Local change detection or deduplication inside utility functions | Utility layer | Must not cross into Runtime state or Engine contracts | No compatibility burden | Keep internal under its current utility name; do not persist in Runtime state, recipes, or HTTP contracts |
| `source_config_hash` | Removed from target Runtime boundary | Former Strategy Engine contract | Hash of the interpreted strategy envelope | Previously used as configuration provenance | Strategy Engine | Must not appear in Runtime requests, responses, state, or recipes | Breaking cleanup allowed; no Runtime backward compatibility | Remove from Runtime ↔ Engine contracts without replacement; Engine cleanup follows the dedicated plan |
| `market_data_hash` | Removed from target Runtime boundary | Former Market Data Service / Strategy Engine contract | Hash of the candle set or bounded market-data coverage used | Previously exposed calculation provenance | Market Data Service | Must not appear in Runtime requests, responses, state, recipes, or journals | Breaking cleanup allowed; no Runtime backward compatibility | Remove from Runtime information exchange without replacement; Engine cleanup follows the dedicated plan |
| `contract_version` | Removed from target Runtime boundary | Former API DTOs | Explicit payload marker | Previously selected or validated a transport schema inside the JSON body | API owner | Must not appear in Runtime requests, responses, state, recipes, journal records, or internal objects | Breaking cleanup allowed; no Runtime backward compatibility | Remove without replacement from Runtime. Version compatibility is owned by the deployed endpoint and OpenAPI schema; Engine cleanup follows plan 27 |
| `trace_id` | Implemented but intentionally unconnected observability hook | Runtime HTTP ingress | New opaque ID per accepted committed-bar request | Reserved for future tracing only | Strategy Runtime | Generated locally and immediately discarded | No backward compatibility required | Renamed from `flow_id`. Do not place it in processing objects, journal records, runtime state, Engine/ABI payloads, results, or errors until a real tracing subsystem is introduced |
| `target_bar_open_time_ms` | Implemented temporal coordinate, not an ID | MDS event; selected by Runtime | Open time of the exact committed target bar | Binds a projection to the precise bar being calculated | MDS supplies fact; Runtime selects/forwards | Runtime → Engine; Engine → Runtime echo | Agreed and required | Keep inside projection request and projected-result context. Do not create a separate projection ID solely to identify this synchronous calculation |
| `source_plan_bar_open_time_ms` | Implemented plan provenance coordinate | Strategy Engine | Target/source bar on which the side plan was produced | Records the origin bar of a concrete entry side plan | Strategy Engine | Engine → Runtime; later may be included in executable plan | Contract can be refined, but semantic fact is required | Keep inside each side plan. It may participate in a composite natural reference, but should not replace a true command ID on async execution boundaries |
| `entry_bar_open_time_ms` | Agreed execution fact | ABI / exchange execution observation | Bar containing actual entry execution | Anchors open-trade bar-to-bar replay | ABI as fact provider; Runtime stores lifecycle fact | ABI → Runtime → Engine | ABI DTO is provisional and has no backward-compatibility requirement | Keep the fact, but freely redesign ABI API and storage around the finalized Runtime lifecycle object |
| `entry_recipe_revision_id` | Proposed only | Proposed Runtime-generated | New opaque ID on every mutable recipe replacement | Would identify one exact mutable recipe snapshot | Strategy Runtime | Potential Runtime ↔ ABI | Not implemented; no compatibility need | Do not introduce now. Synchronous object enrichment does not need it; async execution should be designed around a real command/instruction entity instead |
| `entry_instruction_id` | Candidate future async command identity | Runtime when creating an executable entry instruction | New opaque idempotency/correlation key | Identifies one concrete Runtime instruction sent to ABI | Strategy Runtime | Runtime ↔ ABI; callback back to Runtime | Not implemented. ABI may be broken/refactored to adopt it | Consider only when designing Runtime → ABI async execution. Prefer one generic `command_id` if all command types share the same lifecycle |
| `abi_instruction_correlation` | Proposed ambiguous placeholder | Undefined | Undefined | Unclear whether it identifies a command, order, execution, or position | Undefined | Runtime ↔ ABI | Existing ABI notions are provisional and replaceable | Reject this field/name. Replace it with a specifically modeled entity such as `command_id`, or omit it entirely if callback carries a complete durable reference object |
| `abi_command_id` | Possible future command identity | Preferably Runtime at command creation | Opaque idempotency/correlation key | Identifies one command accepted by ABI | Prefer Runtime ownership; ABI records it | Runtime ↔ ABI | ABI implementation has no backward-compatibility constraint | Choose this or a narrower instruction ID, not both by default. If adopted, make it universal across entry, protection, and close commands |
| existing ABI signal/order correlation IDs | Implemented in early ABI code, exact names may vary | ABI / early Runtime-ABI contract | Existing implementation-specific values | Early request, journal, order, or signal correlation | ABI implementation | Runtime ↔ ABI and ABI internal | Explicitly provisional; no backward compatibility required | Re-audit during ABI cutover. Remove, rename, or replace with canonical Runtime-owned identities and complete request/callback objects |
| `exchange_order_id` | External exchange fact | Bybit | Generated by exchange per order | Identifies one exchange order | Exchange / ABI | ABI ↔ exchange; Runtime only if a later use case requires it | External value itself is immutable fact; ABI representation is refactorable without backward compatibility | Keep inside ABI execution records. Do not promote to Runtime cycle identity or require Runtime to store it unless operational reconciliation needs it |
| `fill_id` / `execution_id` | External exchange fact | Bybit | Generated per fill/execution | Identifies one execution event | Exchange / ABI | ABI internal; optional ABI → Runtime callback details | External fact; surrounding ABI contracts are breaking-changeable | Keep in ABI journal/reconciliation. Runtime receives only when needed for lifecycle facts; never use as recipe, command, position, or cycle identity |
| `position_id` | Not established | Depends on real exchange/ABI model | Undefined | Would identify an exchange position | Exchange / ABI | Potential ABI → Runtime | No implemented canonical contract; no backward compatibility required | Do not invent. If Bybit/ABI lacks a stable position entity, identify Runtime lifecycle through `strategy_instance_id` and `trade_cycle_id` plus position facts |

---

## 3. Consolidation decisions

### 3.1 One long-lived instance identity

Current aliases:

```text
stable_deployment_id
strategy_instance_id
Engine.instance_id
```

Target model:

```text
strategy_instance_id
```

The value is born once at the deployment boundary. Utility, semantic Runtime, Engine DTOs, and ABI DTOs must not independently generate their own version.

Transition rule:

```text
utility deployment value
→ semantic field name strategy_instance_id
→ same value serialized in external request objects
```

The preferred final refactoring is to rename fields rather than preserve three names indefinitely.

### 3.2 One trade-cycle identity

Current candidates:

```text
Runtime.trade_cycle_id
Engine.trade_id
```

Target model:

```text
trade_cycle_id
```

If the Engine audit confirms the existing field is Runtime workflow identity, rename it and remove the alias. Do not create a separate mapping table merely to support an obsolete name.

### 3.3 Keep three provenance hashes distinct

```text
spec_revision_hash   = utility-internal only
source_config_hash   = removed from Runtime boundary
market_data_hash     = removed from Runtime boundary
```

The utility hash remains local. Engine-owned configuration and market-data hashes are removed from the Runtime boundary rather than grouped or correlated.

### 3.4 Do not create IDs for synchronous enrichment stages

The following do not require a new identity merely because they are separate classes or HTTP DTOs:

```text
StrategyBarProcessingUnit
StrategyInstanceRuntimeState
PositionResolvedStrategyInstance
LiveEntryProjectedStrategyInstance
OpenTradeProjectedStrategyInstance
```

They form one object-enrichment chain. The containing object and synchronous call context associate input and output.

A stage-specific ID should be introduced only if the stage becomes independently durable, retryable, asynchronously delivered, or externally addressable.

---

## 4. Refactoring ID exchange through typed entities

### 4.1 `StrategyIdentity`

```text
StrategyIdentity
├── strategy_id
├── strategy_version
└── strategy_instance_id
```

Purpose:

- avoid repeated loose method parameters;
- preserve three genuinely different semantics;
- provide one stable nested object for Engine and internal Runtime contracts.

This does not mean creating a new fourth ID. It groups existing fields.

### 4.2 `MarketIdentity`

```text
MarketIdentity
├── ticker
└── base_timeframe
```

This already corresponds to the Engine `market` object.

### 4.3 Projection context

Runtime retains `target_bar_open_time_ms` as a temporal coordinate. It does not wrap that coordinate with any market-data hash or provenance identifier.

### 4.4 `FrozenEntryContext`

```text
FrozenEntryContext
├── trade_cycle_id
├── StrategyIdentity
├── pinned strategy envelope or immutable spec revision reference
├── EntryRecipe
└── execution facts
    ├── entry_bar_open_time_ms
    └── executed_entry_price
```

Internal Runtime modules should pass this object rather than a flat list of IDs, hashes, fields, and prices.

### 4.5 ABI command and callback objects

Future asynchronous ABI interaction should exchange complete typed objects, for example:

```text
ExecutionCommand
├── command_id              # only if async idempotency/callback requires it
├── strategy_instance_id
├── trade_cycle_id
├── command payload
└── required provenance
```

```text
ExecutionResult
├── command reference       # only the minimum durable reference actually required
├── lifecycle facts
└── exchange facts
```

The design must first determine whether an independent `command_id` is necessary. Existing ABI IDs do not constrain this decision and may be deleted.

---

## 5. Recommended canonical set after refactoring

### Durable business identities

```text
strategy_id
strategy_version
strategy_instance_id
trade_cycle_id
```

### Technical processing / observability

```text
trace_id
```

### Temporal coordinates

```text
target_bar_open_time_ms
source_plan_bar_open_time_ms
entry_bar_open_time_ms
```

### Future asynchronous execution identity

At most one Runtime-owned command identity should be introduced initially, and only if the concrete Runtime ↔ ABI design proves it necessary:

```text
command_id
```

A narrower `entry_instruction_id` should be used instead only if entry instructions have a genuinely distinct persistence and callback lifecycle from all other ABI commands.

Do not introduce all of the following simultaneously:

```text
entry_recipe_revision_id
entry_instruction_id
abi_instruction_correlation
abi_command_id
```

without a distinct entity and lifecycle for each.

---

## 6. ABI Executor Bot refactoring policy

All current ABI-specific contracts and identifiers have this status:

```text
implemented early
provisional
not backward-compatibility constrained
breaking-changeable
subordinate to finalized Runtime architecture
```

Accordingly, the ABI refactor may:

- rename or remove identifiers;
- replace multiple IDs with one Runtime-owned canonical identity;
- replace loose fields with typed request and callback objects;
- alter HTTP endpoints and schemas;
- alter journal and persistence formats;
- discard obsolete signal/order correlation models;
- rebuild instance-to-position mapping;
- remove compatibility aliases rather than perpetuate them.

The only non-negotiable facts are external exchange observations such as order IDs, fill IDs, timestamps, quantities, and prices. Even those facts need not all cross into Runtime.

---

## 7. Open gates

1. Confirm all Strategy Engine `trade_id` usages and rename to `trade_cycle_id` if no distinct meaning exists.
2. Rename Engine `instance_id` to `strategy_instance_id` when updating the Engine contract.
3. Keep any deployment-content hash private to utility implementation and verify that no such hash crosses into Runtime state or Engine contracts.
4. Decide when `trade_cycle_id` is created.
5. Design the actual Runtime → ABI asynchronous command and callback lifecycle.
6. Decide whether that lifecycle needs one universal `command_id`.
7. Re-audit and freely refactor all existing ABI IDs, DTOs, journals, and persistence after the Runtime identity model is finalized.
8. Decide the durable storage location of open-trade projection provenance.

---

## 8. Target identity hierarchy

```text
strategy_id
└── strategy_instance_id
    ├── trade_cycle_id #1
    │   ├── EntryRecipe
    │   ├── PositionManagementRecipe
    │   └── optional command identities only for real async commands
    │
    ├── trade_cycle_id #2
    │   ├── EntryRecipe
    │   ├── PositionManagementRecipe
    │   └── optional command identities only for real async commands
    │
    └── trade_cycle_id #N
```

Processing-stage objects do not receive their own identities merely because they are distinct types. They remain structurally connected through the enrichment pipeline.
