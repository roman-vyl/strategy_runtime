## 1. Pure selector

- [x] 1.1 Add the `utility/deployment_selection` package.
- [x] 1.2 Add `CommittedBarDeploymentSelector`.
- [x] 1.3 Implement exact case-sensitive instrument matching.
- [x] 1.4 Implement exact case-sensitive base-timeframe matching.
- [x] 1.5 Implement deployment-local `enabled` filtering.
- [x] 1.6 Map results to immutable orchestrator-owned `SelectedDeployment` values.
- [x] 1.7 Implement the exact `DeploymentSelectorPort` signature.

## 2. Boundary rules

- [x] 2.1 Ensure the selector performs no filesystem I/O.
- [x] 2.2 Ensure the selector accepts no activation snapshot and performs no activation persistence or reconciliation.
- [x] 2.3 Ensure the selector performs no position, routing, Engine, ABI, or trading logic.
- [x] 2.4 Ensure final dispatch sorting remains owned by the orchestrator.
- [x] 2.5 Ensure no superseded registry or activation class is imported.

## 3. Verification

- [x] 3.1 Test exact instrument and timeframe match.
- [x] 3.2 Test case-sensitive mismatch.
- [x] 3.3 Test disabled deployment exclusion.
- [x] 3.4 Test empty catalog and empty selection.
- [x] 3.5 Test immutable result values.
- [x] 3.6 Test purity and repeatability for identical inputs.
- [x] 3.7 Add an effective architecture test forbidding infrastructure, Engine, ABI, FastAPI, journal, and superseded imports.
- [x] 3.8 Run the full test suite and static checks.
- [x] 3.9 Validate the OpenSpec change strictly.
