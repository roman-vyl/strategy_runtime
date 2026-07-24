## 1. Resolver Models and Ports

- [x] 1.1 Add identity-only `OpenPositionLookupRequest`.
- [x] 1.2 Add strict `OpenPositionLookupResponse` with exact decimal text.
- [x] 1.3 Add transient position-resolved strategy-instance view.
- [x] 1.4 Add ABI lookup and resolver ports plus typed failures.

## 2. Resolver Behavior

- [x] 2.1 Resolve one supplied state with exactly one ABI lookup.
- [x] 2.2 Send only `strategy_instance_id` to ABI.
- [x] 2.3 Enforce open/closed response invariants.
- [x] 2.4 Preserve decimal precision without float conversion.
- [x] 2.5 Propagate typed lookup failures without fabricating position facts.
- [x] 2.6 Perform no routing, Engine call, persistence, or execution action.

## 3. Orchestrator Wiring and Verification

- [x] 3.1 Invoke the resolver after state get-or-create.
- [x] 3.2 Return resolver output into the same semantic orchestration method.
- [x] 3.3 Add tests for identity-only mapping, response invariants, and decimal preservation.
- [x] 3.4 Run the complete Runtime test suite and Python compilation checks.
- [x] 3.5 Run `ruff`, `mypy`, and strict OpenSpec CLI validation.

## 4. Closed Contract and Verification Work

- [x] 4.1 Enforce exact boolean validation for `position_open`.
- [x] 4.2 Distinguish unavailable lookup from malformed ABI protocol data and propagate both typed failures without blanket exception wrapping.
- [x] 4.3 Replace the collection-shaped resolver with a scalar port and test scalar calls, invalid fact combinations, typed failures, and absence of downstream mutation.
