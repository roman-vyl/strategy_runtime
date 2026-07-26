## 1. Shared Exact-Decimal Validation

- [x] 1.1 Expose ABI-compatible non-normalizing exact-decimal and positive exact-decimal predicates in the shared decimal-text module.
- [x] 1.2 Keep ABI entry-package DTOs on the shared predicates without changing wire grammar, required multiplier semantics, or lexeme preservation.
- [x] 1.3 Keep focused shared-helper, ABI model, and ABI contract tests green.

## 2. Runtime-Owned Initial Risk

- [x] 2.1 Remove `risk_multiplier` from `DeploymentSpecification`, catalog parsing, deployment JSON examples, and deployment fixtures.
- [x] 2.2 Remove `risk_multiplier` from `GetOrCreateStrategyInstanceRuntimeStateRequest` and the existing orchestrator registration mapping without changing control flow.
- [x] 2.3 Add an explicitly named internal canonical initial multiplier constant equal to `"1"` at the repository creation boundary.
- [x] 2.4 Create every missing aggregate with exact Runtime-owned multiplier `"1"` and `current_trade_cycle = null`.
- [x] 2.5 Preserve a valid multiplier changed through complete-aggregate `save(...)` across repeated `get_or_create`.
- [x] 2.6 Add tests proving deployment and registration inputs do not own multiplier while Runtime state still validates positive exact-decimal values.

## 3. Minimal Runtime State and Applied Package

- [x] 3.1 Keep required positive exact-decimal `risk_multiplier` on `StrategyInstanceRuntimeState` with no constructor default.
- [x] 3.2 Keep immutable `AppliedEntryPackage` containing only `applied_desired_entry`, `accepted_risk_multiplier`, and `calculated_quantity`.
- [x] 3.3 Validate and preserve applied-package decimal strings without float conversion or lexical normalization.
- [x] 3.4 Keep `CurrentTradeCycle` persisted fields limited to `trade_cycle_id` and nullable `applied_entry_package`.
- [x] 3.5 Keep null cycle/package state free of claims about exchange position existence.

## 4. Unique Trade-Cycle Identity Boundary

- [x] 4.1 Keep the injected `TradeCycleIdFactory` callable boundary and UUID-backed production factory.
- [x] 4.2 Keep production uniqueness, deterministic injection, invalid ID, and no-registration-generation tests.
- [x] 4.3 Keep command, Engine, user, ABI, and exchange identities outside the cycle-ID boundary.

## 5. Repository Load and Complete Save

- [x] 5.1 Keep scalar `get` and complete-aggregate `save` operations on the repository port.
- [x] 5.2 Keep typed missing-state and immutable-registration conflict failures.
- [x] 5.3 Keep in-memory operations atomic under the repository lock with no partial merge, CAS, or hidden keyed-mutex acquisition.
- [x] 5.4 Update repository tests for canonical initial `"1"`, missing lookup, complete replacement, immutable registration conflicts, rediscovery preservation, and individual-operation atomicity.

## 6. Per-Instance Keyed Coordination

- [x] 6.1 Keep context-managed exact-key `StrategyInstanceKeyedMutexRegistry`.
- [x] 6.2 Keep one non-reentrant process-local lock per key without holding the registry guard while waiting.
- [x] 6.3 Keep release guarantees, same-key exclusion, different-key overlap, shared-registry identity, and scope isolation tests.

## 7. Active Documentation

- [x] 7.1 Synchronize the reconciliation master plan with canonical initial `"1"` and non-authoritative null-cycle semantics.
- [x] 7.2 Synchronize the contract map and lifecycle plan with deployment/request boundaries and Runtime-owned risk state.
- [x] 7.3 Update the Markdown delivery map to the minimal I2 `CurrentTradeCycle` and `AppliedEntryPackage` without phases or frozen context.
- [x] 7.4 Restore the canonical deployment example without multiplier and leave delivery-map HTML unchanged.

## 8. Verification and Scope Audit

- [x] 8.1 Run focused catalog, semantic-pipeline, state, repository, identity, mutex, and unchanged ABI contract tests.
- [x] 8.2 Run the complete Runtime pytest suite, Ruff, mypy, and Python compilation checks.
- [x] 8.3 Run strict validation for this change and repository-wide OpenSpec validation.
- [x] 8.4 Confirm by diff and search that catalog/deployment/registration inputs contain no multiplier; Runtime state and ABI still do; canonical initialization is exactly `"1"`; and no risk-update use case, persistence, reconciliation, ABI/Engine contract, router, HTTP, or new orchestration flow was introduced.
