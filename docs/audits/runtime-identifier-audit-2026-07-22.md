> **Superseded identity note (2026-07-23):** historical references to `strategy_version` and `compatibility_profile` describe the pre-simplification contract. Both fields are now removed from Runtime; see `runtime-strategy-selector-fields-removal-decision-2026-07-23.md`.

> **Superseded boundary decision (2026-07-23):** `spec_revision_hash` remains utility-internal only, while `source_config_hash` is removed from the target Runtime ↔ Engine contract. See `runtime-identifier-normalization-and-refactoring-audit-2026-07-22.md`.

# Strategy Runtime Identifier Audit

Date: 2026-07-22
Status: working architectural audit, not an implementation specification

## Purpose

This document inventories the identifiers, hashes, temporal coordinates, and correlation keys currently used or proposed across Strategy Runtime, Strategy Engine, ABI Executor Bot, Market Data Service, and the Runtime utility pipeline.

For each value it records:

- where it is created;
- how it is generated;
- what entity or fact it identifies;
- which module owns its semantics;
- where it is stored;
- whether it crosses service boundaries;
- whether it duplicates another identifier;
- whether it should remain, be renamed, or be deferred.

The goal is to reduce accidental duplication and prevent unrelated concepts such as deployment identity, trade-cycle identity, recipe provenance, exchange order identity, and pipeline tracing from being mixed together.

---

## 1. Identifier inventory

| Identifier | Current status | Created by | Generation / source | Purpose | Semantic owner | Stored in | Cross-module exchange | Audit conclusion |
|---|---|---|---|---|---|---|---|---|
| `strategy_id` | Agreed | Strategy definition / Engine registry | Stable symbolic name such as `ema_pullback` | Identifies the strategy family or algorithm | Strategy Engine / shared contract | Deployment specification, Runtime state | Runtime → Engine | Required. Does not identify a deployed instance |
| `strategy_version` | Agreed | Strategy implementation in Engine | Explicit implementation or contract version | Selects the version of strategy logic | Strategy Engine | Strategy envelope, Runtime snapshot | Runtime → Engine; echoed Engine → Runtime | Required while multiple versions are possible. Not a spec revision |
| `stable_deployment_id` | Implemented in utility contour | Deployment catalog | Stable value read or derived from deployment configuration | Identifies one deployed strategy configuration in utility processing | Runtime utility layer | `DeploymentSpecification`, `StrategyBarProcessingUnit` | Internal Runtime handoff | Same underlying identity as `strategy_instance_id`; should not become a second stored business ID |
| `strategy_instance_id` | Agreed | Runtime deployment catalog | Deterministically derived from strategy semantics + ticker + base timeframe | Identifies one long-lived immutable deployed strategy instance | Strategy Runtime | Key of `StrategyInstanceRuntimeState` | Runtime → ABI; Runtime → Engine | Canonical Runtime identity |
| `instance_id` | Implemented in Engine HTTP DTOs | Not independently generated | Transport field populated from `strategy_instance_id` | Identifies the same long-lived strategy instance | Engine API field name; semantics owned by Runtime | Engine request/response DTOs | Runtime ↔ Engine | Transport alias only. Prefer eventual rename to `strategy_instance_id` |
| `trade_cycle_id` | Agreed conceptually | Strategy Runtime | Runtime-generated opaque ID, likely UUID/ULID | Identifies one complete entry → execution → management → close cycle inside a long-lived instance | Strategy Runtime | `CurrentTradeCycle`, future cycle journal/archive | Runtime → Engine; later Runtime ↔ ABI | Required, but exact creation moment remains open |
| `trade_id` | Present in Engine contract | Currently supplied by caller | Existing Engine field; no independent exchange-derived generation | Intended to correlate one open-trade workflow | Historically Runtime-owned despite ambiguous name | Engine receipt/request/response | Runtime ↔ Engine | Likely duplicate of `trade_cycle_id`. Audit Engine before renaming, but do not create a second Runtime identity |
| `spec_revision_hash` | Planned prerequisite | Runtime deployment catalog | Hash of a canonical deployment specification representation | Identifies the exact Runtime-visible deployment revision | Strategy Runtime / catalog | Deployment specification; future recipe or pinned context | Primarily internal Runtime | Required if Runtime must pin the exact deployment revision. Canonical payload still must be specified |
| `source_config_hash` | Implemented by Engine | Strategy Engine | Canonical hash of `strategy_id`, `strategy_version`, `raw_spec`, and `compatibility_profile` | Identifies the exact strategy configuration as interpreted by Engine | Strategy Engine | Entry recipe / frozen entry context | Engine → Runtime; Runtime → Engine for open-trade validation | Required. Must not be recalculated or replaced by Runtime |
| `market_data_hash` | Implemented contractually | Market Data Service | Hash of the exact candle set / coverage used for a projection | Identifies the market data provenance of a calculation | Market Data Service | Entry recipe or projection metadata; possibly journal | MDS → Engine → Runtime | Useful provenance. Not a routing or business identity |
| `contract_version` | Implemented | Owner of each API | Explicit DTO/API version | Identifies the transport contract version | Each API owner | Request/response DTOs and validation | Cross-service | Required for compatibility. Not related to strategy version |
| `flow_id` | Implemented | Runtime ingress / utility pipeline | New opaque ID per committed-bar processing flow | Correlates one technical pipeline pass | Strategy Runtime | Processing unit, journal, logs | Normally internal Runtime | Keep for tracing. Do not treat as strategy or trade identity |
| `created_by_flow_id` | Planned in state repository | Runtime repository on first creation | Copy of the creating `flow_id` | Records which processing flow created an aggregate | Strategy Runtime | `StrategyInstanceRuntimeState` audit metadata | No cross-service need | Optional audit metadata, not business logic |
| `target_bar_open_time_ms` | Implemented | Originates from MDS closed-bar event | Open time of the exact committed target bar | Binds a projection request to one exact bar | MDS supplies the fact; Runtime selects and forwards it | Processing unit, Engine request | Runtime → Engine; echoed Engine → Runtime | Required temporal coordinate, not an entity ID |
| `source_plan_bar_open_time_ms` | Implemented | Strategy Engine | Bar on which a specific side plan was created | Identifies the bar provenance of an entry side plan | Strategy Engine | `LiveEntryPlan` / `EntryRecipe` | Engine → Runtime; later may enter execution receipt | Required inside the entry plan |
| `entry_bar_open_time_ms` | Agreed | ABI / exchange execution facts | Bar containing actual entry execution | Anchors open-trade bar-to-bar replay | ABI as source of execution fact | Open-position facts / executed entry context | ABI → Runtime → Engine | Required; may differ from source plan bar |
| `entry_recipe_revision_id` | Proposed only | Proposed Runtime-generated | New opaque ID on every mutable recipe replacement | Would identify one exact mutable recipe snapshot | Strategy Runtime | Beside `EntryRecipe` | Potential Runtime ↔ ABI | Do not introduce yet. May be unnecessary if instruction correlation is designed correctly |
| `entry_instruction_id` | Alternative proposal | Runtime at command creation | Opaque ID for a concrete entry instruction sent to ABI | Correlates a specific executable instruction | Strategy Runtime | Future command journal / callback mapping | Runtime ↔ ABI | More promising than assigning IDs to every recipe snapshot; defer until ABI boundary design |
| `abi_instruction_correlation` | Proposed only | Undefined | Undefined | Ambiguous: may refer to command, order, execution, or position | Undefined | Undefined | Runtime ↔ ABI | Reject as a name until the correlated entity is explicitly defined |
| `abi_command_id` | Possible future | Runtime or ABI contract boundary | Opaque idempotency/correlation key for one Runtime command | Identifies one command sent to ABI | Prefer Runtime ownership | Command journal and ABI | Runtime ↔ ABI | Potentially useful universal command identity, but not yet designed |
| `exchange_order_id` | External | Exchange | Generated by Bybit | Identifies one exchange order | Exchange / ABI | ABI journal and exchange records | ABI ↔ exchange; Runtime only if needed | Never use as trade-cycle identity |
| `fill_id` / `execution_id` | External | Exchange | Generated per execution/fill | Identifies one execution event | Exchange / ABI | ABI journal | ABI → Runtime callback only when required | Never use as instruction, position, or cycle identity |
| `position_id` | Not currently established | Depends on exchange/ABI model | Undefined | Would identify an exchange position | Exchange / ABI | Undefined | Potential ABI → Runtime | Do not invent unless a real stable exchange/ABI entity exists |

---

## 2. Confirmed aliases and duplicates

### 2.1 Long-lived instance identity

The following currently name the same underlying entity at different boundaries:

```text
stable_deployment_id
→ strategy_instance_id
→ Engine.instance_id
```

Recommended normalization:

- `strategy_instance_id` is the canonical business name;
- `stable_deployment_id` may remain inside the utility deployment catalog for compatibility;
- `instance_id` may remain temporarily as an Engine transport field;
- only one value is persisted in the semantic Runtime aggregate;
- do not store all three as independent fields.

### 2.2 Trade workflow identity

The current evidence suggests:

```text
Engine.trade_id
≈ Runtime.trade_cycle_id
```

Before changing the Engine contract, audit every `trade_id` use in Engine to confirm that it is not tied to an exchange order, fill, or ABI record.

If confirmed, the preferred resolution is a rename:

```text
trade_id → trade_cycle_id
```

Do not maintain two separately generated IDs with one-to-one mapping unless a real semantic difference is discovered.

---

## 3. Hashes that must remain distinct

The following hashes describe different provenance axes and must not be collapsed into one universal hash:

| Hash | Question answered | Owner |
|---|---|---|
| `spec_revision_hash` | Which exact deployment revision did Runtime load? | Runtime deployment catalog |
| `source_config_hash` | Which strategy configuration did Engine canonically interpret? | Strategy Engine |
| `market_data_hash` | Which exact candle set was used for the calculation? | Market Data Service |

Conceptually:

```text
spec_revision_hash   = deployment provenance
source_config_hash   = strategy interpretation provenance
market_data_hash     = market data provenance
```

They may be grouped in a value object for convenience, but their values and semantics must stay independent.

Suggested internal Runtime value object:

```text
ProjectionProvenance
├── spec_revision_hash
├── source_config_hash
├── market_data_hash
└── target_bar_open_time_ms
```

Not every field must be transmitted across every service boundary. The object is primarily useful inside Runtime state, projected outcomes, and audit journals.

---

## 4. Values that are not business identifiers

These values are often called IDs informally but are not identities of business entities:

| Value | Actual role |
|---|---|
| `contract_version` | Transport compatibility marker |
| `flow_id` | Technical processing trace |
| `target_bar_open_time_ms` | Calculation coordinate |
| `source_plan_bar_open_time_ms` | Entry-plan provenance coordinate |
| `entry_bar_open_time_ms` | Execution-time coordinate |

They should not be used as substitutes for `strategy_instance_id` or `trade_cycle_id`.

---

## 5. Can an entry recipe be identified without a new recipe ID?

A side plan may already be uniquely addressable by a composite identity:

```text
strategy_instance_id
+ source_plan_bar_open_time_ms
+ side
```

This is sufficient only if the invariant holds that an instance produces at most one plan per side per bar.

However, execution correlation is a different problem. A plan may be:

- recalculated;
- replaced;
- sent more than once;
- cancelled;
- superseded before execution.

Therefore the preferred future split is:

```text
recipe identity
= existing instance + bar + side context

execution command identity
= entry_instruction_id or generic command_id
```

Current recommendation:

- do not add `entry_recipe_revision_id` yet;
- design Runtime → ABI instruction and callback semantics first;
- introduce exactly one Runtime-owned command identity if required;
- avoid simultaneous `entry_recipe_revision_id`, `abi_instruction_correlation`, `abi_command_id`, and `entry_instruction_id` unless each identifies a genuinely different entity.

---

## 6. Reducing identifier exchange by passing typed entities

The goal should not be to remove necessary fields, but to stop passing them as unstructured argument lists.

### 6.1 Strategy identity

```text
StrategyIdentity
├── strategy_id
├── strategy_version
└── strategy_instance_id
```

This reduces method-argument clutter while preserving the three distinct meanings.

### 6.2 Market identity

```text
MarketIdentity
├── ticker
└── base_timeframe
```

This already matches the Engine `market` envelope.

### 6.3 Frozen entry context

Instead of passing many independent values between internal Runtime modules, use one typed entity:

```text
FrozenEntryContext
├── trade_cycle_id
├── StrategyIdentity
├── pinned strategy envelope or pinned revision reference
├── EntryRecipe
└── execution facts
    ├── entry_bar_open_time_ms
    └── executed_entry_price
```

This does not eliminate necessary values; it gives them one owner and prevents mismatch.

### 6.4 Projection provenance

```text
ProjectionProvenance
├── spec_revision_hash
├── source_config_hash
├── market_data_hash
└── target_bar_open_time_ms
```

This may accompany an `EntryRecipe` or `PositionManagementRecipe` without mixing provenance into executable business instructions.

---

## 7. Recommended minimum canonical set

### Business identity

```text
strategy_id
strategy_version
strategy_instance_id
trade_cycle_id
```

### Provenance

```text
spec_revision_hash
source_config_hash
market_data_hash
```

### Technical processing

```text
contract_version
flow_id
```

### Temporal coordinates

```text
target_bar_open_time_ms
source_plan_bar_open_time_ms
entry_bar_open_time_ms
```

### Future execution correlation

One identifier only, to be selected during Runtime → ABI design:

```text
command_id
```

or a more specific:

```text
entry_instruction_id
```

Do not introduce multiple overlapping correlation IDs before their entities and lifecycle are defined.

---

## 8. Decisions and open gates

### Agreed or strongly recommended

1. `strategy_instance_id` is the canonical long-lived instance identity.
2. `stable_deployment_id` and Engine `instance_id` are boundary aliases, not new business entities.
3. `trade_cycle_id` is Runtime-owned and identifies one trading cycle.
4. `spec_revision_hash`, `source_config_hash`, and `market_data_hash` remain distinct.
5. Runtime does not calculate or replace Engine `source_config_hash`.
6. Exchange `order_id` and `fill_id` never replace Runtime cycle or command identities.
7. Internal modules should exchange typed entities instead of flat identifier lists.

### Open gates

1. Confirm every Engine `trade_id` use and decide whether to rename it to `trade_cycle_id`.
2. Specify canonical generation rules for `spec_revision_hash`.
3. Decide exactly when `trade_cycle_id` is created.
4. Design Runtime → ABI command and callback correlation.
5. Decide whether the universal future command identity is `command_id` or a narrower `entry_instruction_id`.
6. Decide where open-trade projection provenance is persisted: aggregate state, projected outcome metadata, or journal.

---

## 9. Target hierarchy

```text
strategy_id
└── strategy_instance_id
    ├── trade_cycle_id #1
    │   ├── EntryRecipe
    │   ├── PositionManagementRecipe
    │   └── future command/execution correlations
    │
    ├── trade_cycle_id #2
    │   ├── EntryRecipe
    │   ├── PositionManagementRecipe
    │   └── future command/execution correlations
    │
    └── trade_cycle_id #N
```

Each recipe or projection may carry provenance, but provenance hashes are not additional parent identities in this hierarchy.
