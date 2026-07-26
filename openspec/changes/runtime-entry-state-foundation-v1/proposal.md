## Why

Runtime has a strict ABI entry-package client but still lacks the minimal
Runtime-owned state and coordination boundaries needed by later reconciliation.
I2 must establish those foundations without guessing the deferred ABI fill
contract or changing Engine routing.

## What Changes

- **BREAKING**: Require every deployment document to provide a top-level
  positive exact-decimal string `risk_multiplier`; there is no default and a
  value inside `raw_spec` is not a substitute.
- Carry the deployment-owned `risk_multiplier` into initial
  `StrategyInstanceRuntimeState` while keeping it outside `raw_spec`,
  `registered_spec_snapshot`, and `strategy_instance_id` derivation.
- **BREAKING**: Replace the provisional `CurrentTradeCycle` with the minimal I2
  shape containing only Runtime-owned `trade_cycle_id` and nullable
  `applied_entry_package`.
- Add `AppliedEntryPackage` containing `applied_desired_entry`,
  `accepted_risk_multiplier`, and `calculated_quantity` as one indivisible
  Runtime domain value.
- Define an injected Runtime trade-cycle identity boundary whose production
  implementation generates a distinct opaque ID for every trade cycle.
- Extend the strategy-instance repository with scalar existing-state lookup and
  complete-aggregate save while preserving atomic in-memory operations and
  immutable registration data.
- Add one process-local keyed mutex registry that serializes same-instance
  callers, permits different instances to proceed independently, and releases
  locks on every context exit.
- Keep phases, fills, frozen execution context, position-management state,
  reconciliation, ABI calls, Engine calls, routing changes, HTTP handlers, and
  orchestrator wiring outside I2.

## Capabilities

### New Capabilities

- `current-trade-cycle-state`: Defines the minimal Runtime-owned current-cycle
  model, nested applied entry package, and unique production trade-cycle
  identity boundary.
- `strategy-instance-keyed-coordination`: Defines process-local per-instance
  mutual exclusion for later Runtime state writers.

### Modified Capabilities

- `deployment-catalog`: Requires and validates top-level deployment
  `risk_multiplier`, preserves its exact text, and explicitly excludes it from
  strategy-instance identity derivation.
- `strategy-instance-runtime-state-repository`: Carries the user-provided
  multiplier into initial state and adds scalar load plus complete-aggregate
  save semantics.

## Impact

- Deployment JSON validation, `DeploymentSpecification`, catalog fixtures, and
  deployment identity tests.
- Strategy-instance and minimal trade-cycle state models.
- The repository request, port, in-memory implementation, and tests.
- A new Runtime coordination module and concurrency tests.
- Existing fixtures that omit deployment `risk_multiplier` or construct the
  provisional `CurrentTradeCycle` require migration.
- No Strategy Engine or ABI request contract, use-case router, orchestrator
  control flow or wiring, HTTP endpoint, physical persistence adapter, or
  deployment topology is changed; the existing registration request mapping
  only copies the newly required deployment field.
