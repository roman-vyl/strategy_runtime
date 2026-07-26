## 1. Shared Exact-Decimal Validation

- [ ] 1.1 Move or expose the ABI-compatible non-normalizing exact-decimal and positive exact-decimal predicates in the shared decimal-text module.
- [ ] 1.2 Update the ABI entry-package DTOs to use the shared predicates without changing accepted wire grammar or lexeme preservation.
- [ ] 1.3 Add focused shared-helper tests and keep the existing ABI model and contract tests green.

## 2. Required Deployment Risk Multiplier

- [ ] 2.1 Add required top-level `risk_multiplier` parsing to `FilesystemDeploymentCatalog` with no default or `raw_spec` fallback.
- [ ] 2.2 Reject missing, null, non-string, non-positive, non-finite, whitespace-padded, and otherwise invalid multiplier values as per-file catalog diagnostics.
- [ ] 2.3 Add `risk_multiplier` to immutable `DeploymentSpecification` and preserve every accepted exact-decimal lexeme unchanged.
- [ ] 2.4 Keep `risk_multiplier` outside `raw_spec` and the `strategy_instance_id` derivation inputs.
- [ ] 2.5 Add catalog and identity tests proving multiplier-only changes preserve identity and still participate in duplicate fail-closed handling.
- [ ] 2.6 Update every deployment fixture, example document, and direct `DeploymentSpecification` construction with an explicit valid user multiplier.

## 3. Minimal Runtime State and Applied Package

- [ ] 3.1 Add required positive exact-decimal `risk_multiplier` to `StrategyInstanceRuntimeState` with no constructor default.
- [ ] 3.2 Add immutable `AppliedEntryPackage` containing only `applied_desired_entry`, `accepted_risk_multiplier`, and `calculated_quantity`.
- [ ] 3.3 Validate and preserve applied-package decimal strings without float conversion or lexical normalization.
- [ ] 3.4 Replace the provisional `CurrentTradeCycle` fields with only `trade_cycle_id` and nullable `applied_entry_package`.
- [ ] 3.5 Enforce non-empty opaque cycle identity while keeping cycle/package null states free of exchange-position claims.
- [ ] 3.6 Add focused state-model tests and confirm no phase, fill, frozen-context, or position-management field exists.

## 4. Unique Trade-Cycle Identity Boundary

- [ ] 4.1 Add the injected `TradeCycleIdFactory` callable boundary for later application code.
- [ ] 4.2 Add a production factory backed by Runtime UUID generation that returns a distinct non-empty opaque value for every invocation.
- [ ] 4.3 Add tests for production uniqueness, deterministic test injection, invalid ID rejection, and absence of cycle-ID generation during initial state registration.
- [ ] 4.4 Confirm no `command_id`, Engine `trade_id`, user-authored cycle ID, or exchange-authored cycle ID is introduced.

## 5. Repository Registration, Load, and Complete Save

- [ ] 5.1 Add required `risk_multiplier` to `GetOrCreateStrategyInstanceRuntimeStateRequest` and copy the deployment value in the existing registration request mapping without changing orchestrator control flow.
- [ ] 5.2 Make missing-state creation persist the exact request multiplier with no `"1"` or other fallback.
- [ ] 5.3 Extend `StrategyInstanceRuntimeStateRepository` with scalar `get` and complete-aggregate `save` operations.
- [ ] 5.4 Add typed failures for saving an unregistered identity and attempting to change immutable registration data.
- [ ] 5.5 Implement in-memory `get` and `save` under the existing repository lock with no partial merge, CAS, or hidden keyed-mutex acquisition.
- [ ] 5.6 Preserve stored risk configuration and complete current-cycle state across repeated `get_or_create`.
- [ ] 5.7 Add repository tests for exact initial risk, no default, missing lookup, complete replacement, immutable registration conflicts, repeated discovery, and individual-operation atomicity.

## 6. Per-Instance Keyed Coordination

- [ ] 6.1 Add `StrategyInstanceKeyedMutexRegistry` with context-managed `hold(strategy_instance_id)` and exact-key validation.
- [ ] 6.2 Atomically create one non-reentrant process-local lock per key without holding the registry guard while waiting on an instance lock.
- [ ] 6.3 Guarantee release after normal return and exceptions while keeping the registry free of repository, reconciliation, Engine, ABI, and HTTP behavior.
- [ ] 6.4 Add concurrency tests proving same-key exclusion, different-key overlap, shared-registry lock identity, and release after failure.

## 7. Verification and Scope Audit

- [ ] 7.1 Run focused decimal, deployment-catalog, identity, state, repository, and keyed-coordination tests.
- [ ] 7.2 Run the complete Runtime pytest suite, Ruff, mypy, and Python compilation checks.
- [ ] 7.3 Run strict validation for this change and repository-wide OpenSpec validation.
- [ ] 7.4 Review the diff to confirm no default risk multiplier, fill phase, fill aggregate, frozen context, position-management state, router change, Engine or ABI call, reconciliation, HTTP handler, new orchestrator control flow, durable persistence, CAS, or distributed coordination was introduced.
