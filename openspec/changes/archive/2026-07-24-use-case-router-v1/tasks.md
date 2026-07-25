## 1. Router and Recipe Models

- [x] 1.1 Add immutable singular `DesiredEntry` with nullable projection semantics.
- [x] 1.2 Add immutable desired-protection, close-signal, diagnostics, and `PositionManagementRecipe`.
- [x] 1.3 Add typed position-resolved input and live-entry/open-trade projected outputs.
- [x] 1.4 Add typed projection, Engine-unavailable, identity-binding, response-binding, and missing-open-trade-context failures.

## 2. Engine Request/Response Boundaries

- [x] 2.1 Add live-entry Engine request/response models and port.
- [x] 2.2 Add open-trade Engine request/response models and port.
- [x] 2.3 Map `strategy_id`, derived instance ID, raw spec, ticker, timeframe, and target bar.
- [x] 2.4 Keep version/profile fields, hashes, trade IDs, and Runtime cycle IDs out of transport.
- [x] 2.5 Validate response strategy, market, instance, and target-bar echoes.
- [x] 2.6 Preserve all decimal prices without float conversion.

## 3. Routing and Enrichment

- [x] 3.1 Route solely by current ABI `position_open`.
- [x] 3.2 Route closed positions to live-entry projection.
- [x] 3.3 Route open positions only with a frozen `DesiredEntry` and exact execution facts.
- [x] 3.4 Preserve Engine desired-entry and management objects without interpreting them.
- [x] 3.5 Validate processing-unit, deployment, and resolved-state identity before Engine calls.
- [x] 3.6 Use a scalar router and return no fabricated recipe on failure.
- [x] 3.7 Perform no state application and send no ABI command.

## 4. Semantic Orchestrator and Verification

- [x] 4.1 Implement semantic `StrategyRuntimeOrchestrator`: state → ABI facts → router → Engine projection.
- [x] 4.2 Expose `dispatch` for the utility handoff boundary and `process` for typed projection results.
- [x] 4.3 Test live-entry, open-trade, echo mismatch, missing frozen context, and no-state-application behavior.
- [x] 4.4 Run the complete Runtime test suite and Python compilation checks.
- [x] 4.5 Run `ruff`, `mypy`, and strict OpenSpec CLI validation.

## 5. Closed Contract and Verification Work

- [x] 5.1 Define `StrategyEngineProjectionUnavailable` at the Engine adapter contract and propagate it without blanket exception wrapping.
- [x] 5.2 Enforce the complete processing-unit, deployment, and resolved-state identity chain before Engine calls.
- [x] 5.3 Preserve diagnostics as an opaque recursively immutable JSON mapping with no fixed Runtime field list.
- [x] 5.4 Test scalar routing, both Engine transport failures, both identity links, every response-echo field, opaque diagnostics, and no state mutation.
