## Why

`CommittedBarOrchestrator` requires one pure capability that combines a committed-bar event and a deployment-catalog snapshot into the deployments applicable to that bar. Deployment activation is represented only by the required deployment-local `enabled` flag.

This change introduces that capability directly as `CommittedBarDeploymentSelector`.

## What Changes

- Add a pure `CommittedBarDeploymentSelector`.
- Match accepted deployments by exact instrument and base timeframe.
- Exclude deployments whose required local `enabled` flag is `false`.
- Produce immutable orchestrator-owned `SelectedDeployment` values.
- Keep final dispatch ordering with `CommittedBarOrchestrator`.
- Add isolated unit and architecture tests.

## Capabilities

### New Capabilities

- `deployment-selector`: Selects enabled catalog deployments whose instrument and base timeframe exactly match one committed-bar event.

### Modified Capabilities

None.

## Impact

- Provides the deployment-selection function required by `CommittedBarOrchestrator`.
- Keeps catalog discovery, selection, and dispatch as separate responsibilities.
- Introduces no infrastructure, persistence, Engine, ABI, HTTP, or journal dependency.
