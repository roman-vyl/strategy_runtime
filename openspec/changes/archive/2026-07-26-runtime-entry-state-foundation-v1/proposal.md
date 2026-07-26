## Why

Runtime has a strict ABI entry-package client but still lacks the minimal
Runtime-owned state and coordination boundaries needed by later
reconciliation. I2 must establish those foundations without making deployment
discovery an implicit operational-risk update path or guessing the deferred ABI
fill contract.

## What Changes

- Add Runtime-owned `risk_multiplier` to `StrategyInstanceRuntimeState`.
  Repository registration initializes a missing aggregate with the canonical
  exact-decimal value `"1"`.
- Keep `risk_multiplier` out of deployment JSON,
  `DeploymentSpecification`, registration requests, `raw_spec`,
  `registered_spec_snapshot`, and `strategy_instance_id` derivation.
- Preserve an existing aggregate unchanged during repeated deployment
  discovery, including a multiplier later changed through complete-aggregate
  save.
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
- Keep risk-update APIs, durable persistence, phases, fills, frozen execution
  context, position-management state, reconciliation, ABI calls, Engine calls,
  routing changes, HTTP handlers, and new orchestrator flow outside I2.

## Capabilities

### New Capabilities

- `current-trade-cycle-state`: Defines the minimal Runtime-owned current-cycle
  model, nested applied entry package, and unique production trade-cycle
  identity boundary.
- `strategy-instance-keyed-coordination`: Defines process-local per-instance
  mutual exclusion for later Runtime state writers.

### Modified Capabilities

- `strategy-instance-runtime-state-repository`: Initializes new state with the
  canonical Runtime-owned multiplier and adds scalar load plus
  complete-aggregate save semantics.

## Impact

- Strategy-instance and minimal trade-cycle state models.
- The repository port, in-memory implementation, and tests.
- Shared non-normalizing exact-decimal validation used by Runtime state and
  existing ABI DTOs.
- A new Runtime coordination module and concurrency tests.
- Existing fixtures that construct the provisional `CurrentTradeCycle` require
  migration.
- Deployment-catalog behavior and contracts remain unchanged: deployment does
  not own or transport operational risk.
- No Strategy Engine or ABI contract, use-case router control flow, HTTP
  endpoint, physical persistence adapter, risk-update use case, reconciliation
  workflow, or deployment topology is changed.
