## 1. State Models

- [x] 1.1 Add immutable registered deployment snapshot, current trade-cycle, and strategy-instance aggregate models.
- [x] 1.2 Add typed get-or-create request carrying only first-registration data.
- [x] 1.3 Keep committed-bar coordinates and utility-only deployment hashing out of repository state.

## 2. Repository Boundary

- [x] 2.1 Add `StrategyInstanceRuntimeStateRepository.get_or_create`.
- [x] 2.2 Add an atomic in-memory implementation for the implemented semantic pipeline and tests.
- [x] 2.3 Create missing state with no current trade cycle.
- [x] 2.4 Return existing state unchanged.
- [x] 2.5 Reject conflicting `strategy_id` under one derived `strategy_instance_id`.
- [x] 2.6 Keep physical persistence outside the repository port contract.

## 3. Orchestrator Wiring

- [x] 3.1 Map the exact deployment snapshot from `StrategyBarProcessingUnit`.
- [x] 3.2 Invoke get-or-create exactly once for one semantic processing unit.
- [x] 3.3 Return the state into the same semantic orchestration method.

## 4. Verification

- [x] 4.1 Test first creation, empty trade-cycle state, idempotent lookup, identity conflict, and concurrent equivalent creation.
- [x] 4.2 Run the complete Runtime test suite and Python compilation checks.
- [x] 4.3 Run `ruff`, `mypy`, and strict OpenSpec CLI validation.

## 5. Closed Contract Decisions

- [x] 5.1 Treat the derived `strategy_instance_id` as authoritative and intentionally avoid field-by-field registration-snapshot comparison on an existing key.
- [x] 5.2 Keep the request as a transport DTO and make `RegisteredSpecSnapshot` responsible for validation, detachment, and recursive `raw_spec` freezing.
