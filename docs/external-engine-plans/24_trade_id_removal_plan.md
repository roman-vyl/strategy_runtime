# Strategy Engine `trade_id` Removal Plan

Date: 2026-07-23

Status: planned, not implemented

## 1. Goal

Remove `trade_id` from the Strategy Engine because the audit found that it does not participate in strategy calculations, state lookup, persistence, caching, replay decisions, or routing.

The field currently behaves only as a request-to-response label:

```text
HTTP request
→ ExecutedTradeReceipt.trade_id
→ managed replay arguments/state/result
→ OpenTradeProjectionResult.trade_id
→ HTTP response
```

The target architecture keeps `trade_cycle_id` as a Runtime-owned identity and does not transmit it to Strategy Engine for synchronous open-trade projection.

## 2. Scope

This change removes `trade_id` from:

- active Strategy Engine OpenSpec;
- public domain contracts;
- open-trade application use case;
- EMA pullback open-trade adapter;
- managed replay core;
- HTTP request and response DTOs;
- request validation;
- tests and fixtures;
- current architecture and contract documentation.

Backward compatibility for the removed field is not required. Requests
containing it should be rejected when strict DTO validation is enabled.

## 3. Non-goals

This change does not:

- design Runtime `trade_cycle_id` creation semantics;
- design Runtime ↔ ABI correlation;
- introduce a replacement Engine ID;
- change strategy calculations;
- change stop, take, close-signal, phase, MFE, MAE, or managed-event semantics;
- change market-data loading or target-bar semantics;
- redesign the frozen entry context beyond removing `trade_id`.

## 4. Target contracts

### 4.1 Open-trade request

The Engine request contains only data required for deterministic calculation:

```text
OpenTradeProjectionRequest
├── strategy definition
├── market
├── target_bar_open_time_ms
└── executed_trade_receipt
    ├── strategy/config provenance required by Engine
    ├── side
    ├── source_plan_bar_open_time_ms
    ├── entry_bar_open_time_ms
    ├── planned_entry_price
    ├── executed_entry_price
    ├── initial_stop_price
    ├── initial_take_price
    └── locked_exit_profile
```

It contains no Runtime trade-cycle identity.

### 4.2 Open-trade response

```text
OpenTradeProjectionResponse
├── desired_protection
├── close_signal
├── diagnostics
└── calculation provenance retained by the final contract
```

It contains no `trade_id` and no replacement `trade_cycle_id`.

### 4.3 Managed replay core

Managed replay receives calculation inputs and returns calculation outputs only. It does not carry a caller-owned workflow label through internal state.

## 5. Implementation sequence

### Step 1 — Update the active OpenSpec

Change:

```text
openspec/changes/strategy-live-entry-open-trade-v1/
```

Actions:

1. Remove `trade_id` from `ExecutedTradeReceipt` requirements.
2. Remove `trade_id` from open-trade response requirements.
3. Remove `trade_id` from request and response JSON examples.
4. Remove validation scenarios for blank or missing `trade_id`.
5. Remove echo-validation requirements for `trade_id`.
6. Add an explicit architectural requirement:

   > Open-trade projection is a synchronous calculation contract. Runtime-owned trade-cycle identity is not part of the Strategy Engine request or response.

7. Add a scenario proving the calculation is independent of Runtime trade-cycle identity.
8. Update tasks so contract changes precede code changes.
9. Run strict OpenSpec validation.

Completion criterion:

- no active OpenSpec requirement mentions `trade_id` as part of the Engine contract;
- strict validation passes.

### Step 2 — Remove `trade_id` from public domain models

Primary file:

```text
src/strategy_engine/strategies/contracts.py
```

Actions:

1. Remove `trade_id` from `ExecutedTradeReceipt`.
2. Remove `trade_id` from `OpenTradeProjectionResult`.
3. Remove `trade_id` from any managed-replay public request/result dataclasses located in this file.
4. Update constructors, type hints, serializers, and imports.
5. Preserve all remaining field order and invariants unless a constructor ordering correction is required by Python dataclasses.

Completion criterion:

- no public strategy contract exposes `trade_id`;
- module imports and compilation pass.

### Step 3 — Remove request validation for `trade_id`

Primary file:

```text
src/strategy_engine/strategies/application/validate_open_trade_request.py
```

Actions:

1. Remove `trade_id` from required-string validation.
2. Remove `trade_id`-specific error messages and error codes, if any.
3. Ensure validation still covers every actual calculation prerequisite.
4. Do not replace the removed check with `trade_cycle_id` validation.

Completion criterion:

- validator has no knowledge of Runtime trade-cycle identity;
- all remaining validation tests pass.

### Step 4 — Remove propagation from the open-trade use case

Primary file:

```text
src/strategy_engine/strategies/application/evaluate_open_trade_projection.py
```

Actions:

1. Stop reading `receipt.trade_id`.
2. Stop passing a trade label into the strategy adapter or managed replay.
3. Stop constructing the result with `trade_id`.
4. Verify the use case still returns the exact same business payload:
   - desired protection;
   - close signal;
   - diagnostics;
   - agreed provenance fields.

Completion criterion:

- open-trade application code does not reference `trade_id`;
- business output is unchanged apart from field removal.

### Step 5 — Remove propagation from EMA pullback open-trade projection

Primary file:

```text
src/strategy_engine/strategies/ema_pullback/live_projections/open_trade.py
```

Actions:

1. Remove the `trade_id` argument from calls into managed replay.
2. Remove any local variables used only to carry that value.
3. Keep all actual replay inputs unchanged.
4. Confirm no branch, lookup, or diagnostic calculation depended on the removed value.

Completion criterion:

- EMA projection adapter compiles without `trade_id`;
- projection parity tests remain unchanged except DTO shape.

### Step 6 — Remove `trade_id` from managed replay core

Primary file:

```text
src/strategy_engine/strategies/ema_pullback/managed.py
```

Actions:

1. Remove `trade_id` from `ManagedTradeState`.
2. Remove `trade_id` from `ManagedTradeState.initial(...)`.
3. Remove `trade_id` from `ManagedReplayRequest`, if defined here.
4. Remove `trade_id` from `ManagedReplayResult`.
5. Remove `trade_id` from `to_wire()` or equivalent serialization.
6. Remove the parameter from:
   - `_evaluate_managed_replay_core(...)`;
   - `evaluate_managed_replay(...)`;
   - `evaluate_start_after_entry_managed_projection(...)`;
   - any helper that only forwards it.
7. Remove dead imports and fixture helpers.
8. Confirm no calculation snapshot or managed event requires the label.

Completion criterion:

- a repository-wide source search finds no core-calculation reference to `trade_id`;
- managed replay produces identical trading outputs.

### Step 7 — Remove the field from HTTP DTOs

Primary file:

```text
src/strategy_engine/adapters/http/models.py
```

Actions:

1. Remove `trade_id` from the executed-trade receipt request model.
2. Remove `trade_id` from the open-trade response model.
3. Remove it from managed-replay HTTP models if that API remains active.
4. Ensure strict request models reject unknown extra fields, including the removed `trade_id`.
5. Regenerate or update OpenAPI expectations if snapshots are used.

Completion criterion:

- generated OpenAPI contains no `trade_id` in the affected schemas;
- a request containing only the old extra field is rejected according to the API validation policy.

### Step 8 — Remove HTTP route serialization and mapping

Primary file:

```text
src/strategy_engine/adapters/http/strategy_routes.py
```

Actions:

1. Remove request mapping from HTTP `trade_id` into domain objects.
2. Remove response mapping from domain result to HTTP `trade_id`.
3. Remove any log context that treats it as required business identity.
4. Keep request-scoped technical tracing separate if the service already has it.

Completion criterion:

- route handlers neither accept nor emit `trade_id`;
- synchronous request-response behavior is otherwise unchanged.

### Step 9 — Decide and clean the standalone managed-replay API

Recommended decision: remove `trade_id` from this API in the same change.

Reason:

- the field is also only a label there;
- retaining it would force an unnecessary label through the replay core;
- no backward compatibility is required.

Actions:

1. Remove the field from standalone managed-replay request and response models.
2. Update its route mapping and serializers.
3. Update examples and tests.
4. If the endpoint is obsolete, record a separate deletion decision rather than keeping `trade_id` as a reason to preserve it.

Completion criterion:

- no managed-replay API or core model carries `trade_id`.

### Step 10 — Update tests and fixtures

Expected test areas:

```text
tests/test_open_trade_projection_api.py
tests/test_open_trade_receipt_validation.py
tests/test_open_trade_projection_composition.py
tests/test_ema_pullback_start_after_entry_managed.py
```

Also update all repository matches found by search.

Actions:

1. Remove `trade_id` from request fixtures.
2. Remove response assertions for echoed `trade_id`.
3. Delete blank/missing `trade_id` validation tests.
4. Remove `trade_id` from managed replay fixtures and expected wire payloads.
5. Add a strict-contract test:

   ```text
   old request containing trade_id
   → rejected as an unsupported extra field
   ```

6. Add a calculation parity test comparing pre-removal golden output with post-removal output after stripping the removed field.
7. Add a structural test ensuring OpenAPI does not expose `trade_id` in affected schemas.
8. Run the full test suite, not only open-trade tests.

Completion criterion:

- all tests pass;
- no test fixture relies on `trade_id`;
- business calculations remain identical.

### Step 11 — Update current documentation

Current documents to review:

```text
docs/20_runtime_open_trade_management_audit.md
docs/21_runtime_open_trade_management_plan.md
docs/22_live_projections_architecture.md
docs/23_live_contract_closure_decisions.md
docs/master-plan.md
```

Actions:

1. Remove `trade_id` from current request and response examples.
2. State that trade-cycle identity belongs to Runtime.
3. State that Strategy Engine operates as a synchronous calculation service and does not own Runtime lifecycle identity.
4. Do not rewrite historical archived OpenSpec unless repository policy explicitly requires it.
5. Add a short decision record or closure note linking the audit to this removal.

Completion criterion:

- current normative documentation contains no contradictory active contract.

### Step 12 — Update Runtime planning documents and gates

After the Engine change is implemented, update Strategy Runtime documents:

1. Remove the open gate concerning `trade_id ↔ trade_cycle_id` mapping.
2. Remove `trade_id` from the Runtime open-trade request design.
3. Remove `trade_id` from response echo validation.
4. Keep `trade_cycle_id` inside Runtime state and future Runtime ↔ ABI design.
5. Record that no replacement ID crosses the Runtime → Engine boundary.

Completion criterion:

- Runtime and Engine documents describe the same boundary.

### Step 13 — Static and repository-wide verification

Run:

```text
pytest
ruff check .
mypy src
openspec validate strategy-live-entry-open-trade-v1 --strict
```

Also run repository searches:

```text
rg -n "trade_id" src tests openspec/changes/strategy-live-entry-open-trade-v1 docs
rg -n '"trade_id"' .
```

Classify remaining matches:

- active code: must be zero;
- active contract/tests: must be zero;
- current normative docs: must be zero;
- archived/historical evidence: may remain when intentionally preserved and clearly marked historical.

Completion criterion:

- all available checks pass;
- every remaining textual match is explained.

## 6. Migration policy

No compatibility layer is required.

Do not add:

- deprecated aliases;
- dual request schemas;
- `trade_id` to `trade_cycle_id` mapping;
- fallback acceptance of the old field;
- response duplication.

The API change is intentionally breaking because no production consumer requires
the removed contract.

## 7. Risks and controls

### Risk: an indirect diagnostic consumer expects `trade_id`

Control:

- repository-wide search across code, tests, docs, OpenAPI, and serializers;
- inspect structured logging and exported diagnostic payloads.

### Risk: calculation parity changes accidentally during signature cleanup

Control:

- golden parity test on desired protection, close signal, diagnostics, and managed events;
- keep calculation changes out of the same patch.

### Risk: standalone managed-replay API is overlooked

Control:

- remove the field from core first, forcing every remaining caller to fail until updated.

### Risk: Runtime documentation continues to require a mapping

Control:

- make Runtime gate removal an explicit completion step.

## 8. Definition of done

The change is complete when all conditions hold:

1. Strategy Engine accepts and computes open-trade projections without `trade_id`.
2. Strategy Engine does not accept or return `trade_id` in active HTTP contracts.
3. Managed replay core contains no caller-owned trade label.
4. No replacement `trade_cycle_id` is added to Engine.
5. Trading outputs are unchanged apart from removal of the field.
6. Active OpenSpec validates strictly.
7. Full tests and available static checks pass.
8. Runtime documentation no longer contains a `trade_id ↔ trade_cycle_id` gate.
9. Remaining `trade_id` matches, if any, exist only in clearly historical archives.

## 9. Recommended patch boundaries

To keep review clear, use three commits or patch groups:

### Patch A — Contract and OpenSpec

- active OpenSpec;
- domain DTOs;
- HTTP models;
- validation.

### Patch B — Core propagation removal

- application use case;
- EMA adapter;
- managed replay core;
- routes and serializers.

### Patch C — Tests and documentation

- fixtures and contract tests;
- parity verification;
- Engine documentation;
- Runtime gate cleanup.

All three patches belong to one atomic feature change and should not leave the main branch with mismatched public contracts and implementation.
