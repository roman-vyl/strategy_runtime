# Strategy Engine and ABI Executor API/Data Audit

Status: in progress. Strategy Engine has been audited from the available source snapshot. The ABI Executor source snapshot is not present in the current sandbox, so the ABI section is explicitly preliminary and based only on the previously established public contract; it must be replaced by a source-level audit when the repository snapshot is available.

## Agreed execution boundary

The live pipeline uses a neutral decision boundary:

```text
Strategy Engine
        |
        | neutral strategy decision
        v
Strategy Runtime
        |
        | map decision to ABI signal contract
        v
ABI Executor
        |
        | calculate quantity and execute
        v
Bybit
```

Agreed responsibilities:

- Strategy Engine decides what the strategy wants to do.
- Strategy Runtime adapts that neutral strategy decision to the ABI Executor input contract.
- ABI Executor owns quantity calculation and exchange execution.
- Strategy Runtime must not calculate quantity.
- Strategy Engine must not depend on ABI-specific or Bybit-specific request models.

A possible future extension may add a neutral relative exposure or risk-unit field between Strategy Runtime and ABI Executor, allowing ABI to reduce position size for riskier or more volatile assets. No field, scale, or sizing rule is approved yet.

## Strategy Engine source audit

Audited snapshot: `strategy_engine_final(1).zip`.

### Existing HTTP entry points

The Strategy Engine currently exposes range-oriented strategy endpoints:

```text
POST /v1/strategy-evaluations/range
POST /v1/strategy-evaluations/range-batch
POST /v1/strategy-evaluations/managed-replay
```

The current range request is represented by `StrategyRangeRequestModel` and contains:

```text
market:
    ticker
    base_timeframe
    from_ms
    to_ms
strategy:
    strategy_id
    strategy_version
    instance_id
    raw_spec
    compatibility_profile
expected_market_data_hash
options
```

This contract is appropriate for bounded backtest/research evaluation but does not match the agreed runtime request semantics because runtime does not provide a range or triggering-bar identity.

### Existing strategy envelope

The reusable part is `StrategySpecEnvelope`:

```text
strategy_id
strategy_version
instance_id
raw_spec
compatibility_profile
```

It also derives a canonical `config_hash` from strategy identity, version, raw spec, and compatibility profile.

This envelope is a strong candidate for reuse in the future runtime-facing Engine request. The Runtime identity decision is now fixed: `strategy_id` identifies the family, `instance_id` identifies the stable live instance, and `config_hash` fingerprints its current configuration. Runtime activation is keyed by `instance_id`; an edited configuration may change `config_hash` without changing `instance_id` or resetting `is_active`.


### Identity semantics confirmed from current Engine and legacy BBB

The current Engine intentionally excludes `instance_id` from canonical `config_hash` generation. Therefore two differently named instances with identical strategy semantics may share a `config_hash`, while editing parameters under the same `instance_id` changes the `config_hash`.

Legacy BBB likewise separated a human/operational `instance_id` from a content-derived configuration identifier. Runtime v1 preserves that distinction:

```text
strategy_id  -> strategy family
instance_id  -> stable runtime instance
config_hash  -> current configuration fingerprint
```

This identity split is suitable for the smoke-test case of multiple EMA Pullback instances with different parameters.

### Existing evaluation orchestration

`EvaluateStrategyRange` currently:

1. validates range alignment;
2. resolves the strategy evaluator by `strategy_id`;
3. validates the strategy spec;
4. calls the registered range evaluator.

The EMA pullback evaluator then:

1. builds the feature plan from the spec;
2. asks the indicator evaluator for market data over the supplied range;
3. calculates contexts;
4. calculates direction and blockers;
5. calculates setups;
6. calculates triggers;
7. calculates risk masks and entry arrays;
8. calculates exit-policy arrays;
9. returns a range result.

This confirms that Strategy Engine already owns spec interpretation and component calculation. Runtime must not duplicate these steps.

### Existing result shape

The serialized range result is versioned as:

```text
strategy_evaluation.v1
```

It contains:

```text
strategy identity and config hash
market range and market_data_hash
features
contexts
entries
exit_policy
component_evidence
validity
state_artifact
warnings
```

For EMA pullback, `entries` currently has this shape:

```json
{
  "long": [false, true, false],
  "short": [false, false, false]
}
```

The response therefore exposes arrays over a range. It does not yet expose a standalone neutral current-point decision such as:

```text
no_action
open_position
manage_position
exit_position
```

No exact replacement enum or payload is approved by this audit.

### Important current limitation

The current Engine code computes strategy entry permission and exit-policy data, but does not yet provide a complete runtime execution decision contract ready to map directly to ABI.

In particular, the current audited result does not establish one compact current-point object containing all data needed for live execution, such as:

```text
side
entry intent and trigger semantics
stop-loss intent
take-profit intent
position-management or exit intent
strategy/runtime provenance
```

Therefore the future Engine adaptation should occur at the Engine boundary: add a current-point orchestration path that reuses the same component/evaluator logic but returns a neutral current-point strategy decision rather than a range-shaped research report.

### What should be reused

The future runtime-facing Engine path should reuse, rather than duplicate:

- `StrategySpecEnvelope` semantics;
- strategy registry and spec validation;
- feature-plan construction;
- indicator evaluation;
- context, blocker, setup, trigger, risk-entry, and exit-policy logic;
- canonical config hashing;
- MDS client boundary.

### What should not leak into Runtime

Runtime should not receive or interpret full diagnostic arrays merely to recover the final action. In particular, Runtime should not duplicate knowledge of:

- which entry array represents a valid signal;
- how blockers, setups, and triggers compose;
- how exit-policy components compose;
- how to select the current point from strategy internals;
- how much historical data each component requires.

That reduction must be performed by Strategy Engine itself.

## ABI Executor audit status

A source-level ABI audit could not be completed because no ABI repository/archive is present in the current sandbox or retrievable File Library results.

The previously established external contract indicates:

```text
POST /signals
```

with signal concepts including:

```text
signal_id
instance_id
strategy_id
symbol
side
entry
stop_loss
take_profit
```

Known entry semantics include stop-market trigger price and trigger direction. Known execution behaviour includes fixed smoke quantity today and a planned transition toward balance/stop-based sizing.

These statements are not a substitute for a code audit. Before Runtime implementation, the ABI source must be inspected for:

- exact request schema and validation;
- required versus optional fields;
- quantity ownership in the live code path;
- signal idempotency behaviour;
- accepted entry, stop, take, manage, and exit variants;
- response statuses and error schema;
- journal/state transitions;
- duplicate signal handling;
- position-instance semantics;
- whether one Strategy Engine decision can map to more than one ABI request.

## Confirmed boundary after the partial audit

```text
Engine current-point endpoint (future adaptation)
        |
        | neutral decision; no quantity
        v
Runtime mapping layer
        |
        | ABI-native signal; still no locally calculated quantity
        v
ABI Executor
        |
        | quantity calculation and execution policy
        v
exchange
```

## Questions reserved for internal Runtime design

The following must be discussed only after the ABI source audit is complete:

- the minimum internal decision model Runtime needs;
- whether Runtime stores full Engine responses or only mapping outcomes;
- how one neutral Engine decision maps to ABI entry/manage/exit requests;
- where provenance fields are attached;
- how retries and duplicate delivery interact with ABI idempotency;
- whether Runtime needs persistent processing records;
- whether Runtime processes strategies serially or concurrently;
- what constitutes successful completion of one base-bar evaluation.

## Implementation Gate 01 — Strategy Engine runtime contract adaptation

Status: mandatory pre-implementation gate.

Strategy Runtime implementation must not begin until the Strategy Engine runtime-facing contract has been explicitly designed and approved.

The current Engine API is range-oriented and returns research-shaped arrays and diagnostics. The agreed runtime semantics require a different boundary:

- Runtime sends the active strategy spec and runtime binding, but no bounded time range;
- Runtime does not send triggering-bar identity as the calculation boundary;
- Engine determines the strategy's required streams from the spec;
- Engine reads the latest canonical data for those streams while they are `ready`;
- Engine computes the current strategy point;
- Engine returns a neutral current-point decision that Runtime can map to the ABI Executor contract;
- quantity remains owned by ABI Executor.

Before any Runtime code is implemented, the following must be designed and approved:

1. the runtime request contract exposed by Strategy Engine;
2. the neutral current-point response contract;
3. how the new path reuses the existing backtest evaluator without duplicating strategy logic;
4. the exact boundary between Engine decision semantics and Runtime-to-ABI mapping;
5. error semantics for unavailable Engine/MDS data and invalid specs;
6. compatibility and versioning with the existing range endpoints.

Explicit rule:

> Strategy Runtime implementation is blocked until the Strategy Engine runtime contract adaptation is designed and approved.

This gate is architectural, not an implementation TODO. It must be resolved before choosing Runtime package structure, persistence, retries, orchestration classes, or endpoint implementation.
## Audit finding: historical Engine-to-Abi assumption

The Engine documentation and OpenSpec were reviewed for a direct Strategy Engine → Abi contract. No approved direct integration was found. The historical target already placed a future Runtime wrapper between Strategy Engine and Abi and assigned Abi delivery to that wrapper.

The review did find earlier assumptions about the Runtime wrapper that no longer match the approved architecture:

- incremental `evaluate_bar` with caller-supplied previous indicator, strategy, and position state;
- Engine-hosted runtime strategy-instance endpoints;
- checkpoint/replay and confirmed-bar ordering as already-fixed Runtime responsibilities;
- wording such as `BBB/Abi own actual execution`, which can be misread as a direct Engine → Abi seam.

These are now marked **decision under review** in the extracted Engine documentation. They are not implementation requirements. The preserved boundary is:

```text
Strategy Engine
    -> neutral strategy decision
Strategy Runtime
    -> ABI signal adaptation and orchestration
ABI Executor
    -> quantity calculation and exchange execution
```

Before implementation, the Strategy Engine current-point request/response contract must be designed and approved. That design must explicitly supersede or re-approve the earlier incremental-session assumptions.


## Mandatory ABI execution-lifecycle audit

Before Runtime-to-ABI delivery semantics are implemented, the ABI source must be audited specifically for the complete accepted-signal lifecycle: acceptance, exchange placement attempts, retry policy, exchange confirmation, journal transitions, duplicate handling, reconciliation, and restart recovery.

The audit must identify the precise ABI response that transfers responsibility from Runtime to ABI.

Agreed rule:

> After ABI confirms acceptance, Runtime does not track or manage the later exchange outcome. ABI owns all subsequent delivery, retry, confirmation, and recovery behaviour.

This audit is a formal implementation gate, not optional background research. See `implementation-gates.md`.
